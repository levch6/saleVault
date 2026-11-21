"""Run lifecycle for one site: warm-up, segment planning, page fetching, completeness check."""

import asyncio
import logging
import math
import random
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from salevault.domain.models import Gender, ProductRecord
from salevault.scraper.base import PageResult, Segment, SiteAdapter
from salevault.scraper.errors import BlockedError, BudgetExceededError, TransientError
from salevault.scraper.segmentation import PlannedSegment, plan_segments

log = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
RawSink = Callable[[Segment, int, str], None]


@dataclass(frozen=True, slots=True)
class RunOptions:
    concurrency: int = 1
    delay_range_s: tuple[float, float] = (0.8, 1.6)
    """Random politeness pause after every request of a worker."""
    max_requests: int = 3000
    max_retries: int = 4
    """Retries for transient errors, with exponential backoff 2, 4, 8, 16 s."""
    block_pause_s: float = 60.0
    """One pause on 403/429 before giving up."""
    safe_limit_ratio: float = 0.96
    """Segment size limit as a share of the API cap, leaving room for catalog drift."""
    max_pages_per_segment: int | None = None
    """Debug limit; a limited run is never considered complete."""
    segment_completeness: float = 0.98
    total_completeness: float = 0.99


class ProgressListener(Protocol):
    def on_planning(self, requests: int) -> None: ...

    def on_planned(self, segments: int, pages_total: int) -> None: ...

    def on_page(self, pages_done: int, items_seen: int) -> None: ...


class NullProgress:
    def on_planning(self, requests: int) -> None:
        pass

    def on_planned(self, segments: int, pages_total: int) -> None:
        pass

    def on_page(self, pages_done: int, items_seen: int) -> None:
        pass


@dataclass(frozen=True, slots=True)
class SegmentReport:
    key: str
    expected: int
    fetched: int
    pages: int
    truncated: bool

    @property
    def ratio(self) -> float:
        return 1.0 if self.expected == 0 else self.fetched / self.expected


@dataclass(slots=True)
class ScrapeResult:
    site: str
    started_at: datetime
    finished_at: datetime
    expected_total: int
    items: dict[str, ProductRecord]
    genders: dict[str, Gender]
    segments: list[SegmentReport]
    requests: int
    retries: int
    invalid_items: int
    limited: bool
    segment_threshold: float
    total_threshold: float

    @property
    def completeness(self) -> float:
        return 1.0 if self.expected_total == 0 else len(self.items) / self.expected_total

    @property
    def complete(self) -> bool:
        return (
            not self.limited
            and self.completeness >= self.total_threshold
            and all(not s.truncated and s.ratio >= self.segment_threshold for s in self.segments)
        )


@dataclass(slots=True)
class _Collector:
    items: dict[str, ProductRecord] = field(default_factory=dict)
    genders: dict[str, Gender] = field(default_factory=dict)
    per_segment: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    invalid: int = 0

    def add(self, segment: Segment, gender: Gender, page: PageResult) -> None:
        seen = self.per_segment[segment.key]
        self.invalid += page.invalid_items
        for item in page.items:
            self.items[item.external_id] = item
            self.genders[item.external_id] = self.genders.get(item.external_id, Gender(0)) | gender
            seen.add(item.external_id)


class ScrapeRunner:
    def __init__(
        self,
        adapter: SiteAdapter,
        options: RunOptions | None = None,
        *,
        progress: ProgressListener | None = None,
        raw_sink: RawSink | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._adapter = adapter
        self._opts = options or RunOptions()
        self._progress = progress or NullProgress()
        self._raw_sink = raw_sink
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._requests = 0
        self._retries = 0

    @property
    def safe_limit(self) -> int:
        return int(self._adapter.page_size * self._adapter.max_pages * self._opts.safe_limit_ratio)

    async def run(self) -> ScrapeResult:
        started = datetime.now(UTC)
        await self._adapter.warm_up()

        root = await self._request(Segment(), 1)
        roots = self._adapter.root_segments(root) or [Segment()]
        planned = await plan_segments(
            self._planning_fetch,
            roots,
            limit=self.safe_limit,
            fallback_price_range=root.facets.price_range,
            known_first_pages={Segment(): root},
        )

        collector = _Collector()
        jobs: list[tuple[Segment, int]] = []
        pages_per_segment: dict[str, int] = {}
        limited = False
        for p in planned:
            collector.add(p.segment, self._adapter.gender_of(p.segment), p.first_page)
            pages = self._pages_for(p.count)
            if self._opts.max_pages_per_segment is not None:
                limited = limited or pages > self._opts.max_pages_per_segment
                pages = min(pages, self._opts.max_pages_per_segment)
            pages_per_segment[p.segment.key] = pages
            jobs.extend((p.segment, page) for page in range(2, pages + 1))

        pages_total = len(planned) + len(jobs)
        pages_done = len(planned)
        self._progress.on_planned(len(planned), pages_total)
        self._progress.on_page(pages_done, len(collector.items))
        log.info(
            "Planned %d segments, %d pages (%d expected items)",
            len(planned),
            pages_total,
            root.count,
        )

        queue: asyncio.Queue[tuple[Segment, int]] = asyncio.Queue()
        for job in jobs:
            queue.put_nowait(job)

        async def worker() -> None:
            nonlocal pages_done
            while True:
                try:
                    segment, page = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                result = await self._request(segment, page)
                collector.add(segment, self._adapter.gender_of(segment), result)
                pages_done += 1
                self._progress.on_page(pages_done, len(collector.items))

        try:
            async with asyncio.TaskGroup() as group:
                for _ in range(max(1, self._opts.concurrency)):
                    group.create_task(worker())
        except ExceptionGroup as eg:
            raise eg.exceptions[0] from None

        return ScrapeResult(
            site=self._adapter.code,
            started_at=started,
            finished_at=datetime.now(UTC),
            expected_total=root.count,
            items=collector.items,
            genders=collector.genders,
            segments=[self._report(p, collector, pages_per_segment) for p in planned],
            requests=self._requests,
            retries=self._retries,
            invalid_items=collector.invalid,
            limited=limited,
            segment_threshold=self._opts.segment_completeness,
            total_threshold=self._opts.total_completeness,
        )

    def _pages_for(self, count: int) -> int:
        return min(max(1, math.ceil(count / self._adapter.page_size)), self._adapter.max_pages)

    @staticmethod
    def _report(
        planned: PlannedSegment, collector: _Collector, pages: dict[str, int]
    ) -> SegmentReport:
        key = planned.segment.key
        return SegmentReport(
            key=key,
            expected=planned.count,
            fetched=len(collector.per_segment[key]),
            pages=pages[key],
            truncated=planned.truncated,
        )

    async def _planning_fetch(self, segment: Segment, page: int) -> PageResult:
        result = await self._request(segment, page)
        self._progress.on_planning(self._requests)
        return result

    async def _request(self, segment: Segment, page: int) -> PageResult:
        """One logical request: transient retries with backoff, one pause on a block."""
        blocked_once = False
        while True:
            try:
                retrying = AsyncRetrying(
                    retry=retry_if_exception_type(TransientError),
                    stop=stop_after_attempt(self._opts.max_retries + 1),
                    wait=wait_exponential(multiplier=2, max=16) + wait_random(0, 1),
                    sleep=self._sleep,
                    before_sleep=self._log_retry,
                    reraise=True,
                )
                result: PageResult = await retrying(self._attempt, segment, page)
            except BlockedError as exc:
                if blocked_once:
                    raise
                blocked_once = True
                self._retries += 1
                log.warning(
                    "Blocked by site on %s p%d (%s); pausing %.0f s once",
                    segment.key,
                    page,
                    exc,
                    self._opts.block_pause_s,
                )
                await self._sleep(self._opts.block_pause_s)
                continue
            await self._sleep(self._rng.uniform(*self._opts.delay_range_s))
            return result

    async def _attempt(self, segment: Segment, page: int) -> PageResult:
        if self._requests >= self._opts.max_requests:
            raise BudgetExceededError(f"Request budget of {self._opts.max_requests} exhausted")
        self._requests += 1
        result = await self._adapter.fetch_page(segment, page)
        if self._raw_sink is not None:
            self._raw_sink(segment, page, result.raw)
        return result

    def _log_retry(self, state: RetryCallState) -> None:
        self._retries += 1
        exc = state.outcome.exception() if state.outcome else None
        wait = state.next_action.sleep if state.next_action else 0.0
        log.warning("Transient error (%s); retry %d in %.1f s", exc, state.attempt_number, wait)
