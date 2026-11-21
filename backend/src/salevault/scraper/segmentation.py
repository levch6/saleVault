"""Split the catalog into segments that fit the API's per-query cap (ADR-0003)."""

import logging
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from salevault.scraper.base import PageResult, Segment

log = logging.getLogger(__name__)

FetchPage = Callable[[Segment, int], Awaitable[PageResult]]


@dataclass(frozen=True, slots=True)
class PlannedSegment:
    segment: Segment
    count: int
    first_page: PageResult
    truncated: bool = False
    """Above the cap but impossible to split further (single price point)."""


async def plan_segments(
    fetch: FetchPage,
    roots: Sequence[Segment],
    *,
    limit: int,
    fallback_price_range: tuple[int, int] | None,
    known_first_pages: dict[Segment, PageResult] | None = None,
) -> list[PlannedSegment]:
    """Fetch page 1 of each candidate and bisect by price until every segment has <= limit items.

    Price bounds are integers and never overlap: [low, mid] and [mid + 1, high].
    """
    known = dict(known_first_pages or {})
    queue: deque[Segment] = deque(roots)
    planned: list[PlannedSegment] = []

    while queue:
        segment = queue.popleft()
        first = known.pop(segment, None) or await fetch(segment, 1)
        if first.count <= limit:
            planned.append(PlannedSegment(segment, first.count, first))
            continue

        bounds = segment.price or first.facets.price_range or fallback_price_range
        if bounds is None or bounds[0] >= bounds[1]:
            log.warning(
                "Segment %s has %d items but cannot be split further; it will be truncated",
                segment.key,
                first.count,
            )
            planned.append(PlannedSegment(segment, first.count, first, truncated=True))
            continue

        low, high = bounds
        mid = (low + high) // 2
        log.debug("Splitting %s (%d items) at %d", segment.key, first.count, mid)
        queue.extend([segment.with_price(low, mid), segment.with_price(mid + 1, high)])

    return planned
