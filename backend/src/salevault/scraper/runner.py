"""Run lifecycle for one site: warm-up, segment planning, page fetching, completeness check."""

import asyncio
import heapq
import logging
import math
import random
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, Self

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from salevault.domain.models import CategoryNode, Gender, ProductRecord
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
    keep_items: bool = True
    """Keep every normalized item in memory (dry runs, JSONL export). Persisted runs don't need
    it: items are staged in the DB, and the summary uses the running top and histogram."""


TOP_SIZE = 50


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    """A planned segment; serializable so an interrupted run can be resumed."""

    segment: Segment
    count: int
    pages: int
    """Pages to fetch, after any debug limit."""
    full_pages: int
    truncated: bool = False

    @property
    def limited(self) -> bool:
        return self.pages < self.full_pages

    def to_json(self) -> dict[str, Any]:
        return {
            "sex": self.segment.sex,
            "price": list(self.segment.price) if self.segment.price else None,
            "count": self.count,
            "pages": self.pages,
            "full_pages": self.full_pages,
            "truncated": self.truncated,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        price = data.get("price")
        return cls(
            segment=Segment(
                sex=data.get("sex"), price=(int(price[0]), int(price[1])) if price else None
            ),
            count=int(data["count"]),
            pages=int(data["pages"]),
            full_pages=int(data["full_pages"]),
            truncated=bool(data.get("truncated", False)),
        )


@dataclass(frozen=True, slots=True)
class ResumeState:
    """What an interrupted run already has: its plan, fetched pages and staged items."""

    expected_total: int
    plan: tuple[SegmentPlan, ...]
    done_pages: Mapping[tuple[str, int], Sequence[str]]
    """(segment key, page) -> ids of the items on that page."""
    genders: Mapping[str, Gender]
    """Every staged item id with its gender bits."""
    discount_counts: Mapping[int, int] = field(default_factory=dict)
    top: Sequence[ProductRecord] = ()
    items: Mapping[str, ProductRecord] | None = None
    """Only loaded when the run keeps items in memory."""


class RunSink(Protocol):
    """Receives the plan and every fetched page as they happen (e.g. to stage them in the DB)."""

    def on_plan(self, expected_total: int, plan: Sequence[SegmentPlan]) -> None: ...

    def on_category_tree(self, nodes: Sequence[CategoryNode]) -> None: ...

    def on_page(self, segment: Segment, page: int, gender: Gender, result: PageResult) -> None: ...


class NullSink:
    def on_plan(self, expected_total: int, plan: Sequence[SegmentPlan]) -> None:
        pass

    def on_category_tree(self, nodes: Sequence[CategoryNode]) -> None:
        pass

    def on_page(self, segment: Segment, page: int, gender: Gender, result: PageResult) -> None:
        pass


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
    item_count: int
    genders: dict[str, Gender]
    discount_counts: dict[int, int]
    """Unique items per discount percent."""
    top: list[ProductRecord]
    """Biggest discounts first (at most TOP_SIZE)."""
    items: dict[str, ProductRecord] | None
    segments: list[SegmentReport]
    requests: int
    retries: int
    invalid_items: int
    limited: bool
    segment_threshold: float
    total_threshold: float

    @property
    def completeness(self) -> float:
        return 1.0 if self.expected_total == 0 else self.item_count / self.expected_total

    @property
    def complete(self) -> bool:
        return (
            not self.limited
            and self.completeness >= self.total_threshold
            and all(not s.truncated and s.ratio >= self.segment_threshold for s in self.segments)
        )


@dataclass(slots=True)
class _Collector:
    keep_items: bool = True
    items: dict[str, ProductRecord] = field(default_factory=dict)
    genders: dict[str, Gender] = field(default_factory=dict)
    per_segment: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    invalid: int = 0
    discount_counts: Counter[int] = field(default_factory=Counter)
    _top: list[tuple[int, int, str, ProductRecord]] = field(default_factory=list)

    def add(self, segment: Segment, gender: Gender, page: PageResult) -> None:
        seen = self.per_segment[segment.key]
        self.invalid += page.invalid_items
        for item in page.items:
            if item.external_id not in self.genders:
                self._count(item)
            if self.keep_items:
                self.items[item.external_id] = item
            self.genders[item.external_id] = self.genders.get(item.external_id, Gender(0)) | gender
            seen.add(item.external_id)

    def _count(self, item: ProductRecord) -> None:
        self.discount_counts[item.discount_pct] += 1
        entry = (item.discount_pct, item.savings_minor, item.external_id, item)
        if len(self._top) < TOP_SIZE:
            heapq.heappush(self._top, entry)
        elif entry[:3] > self._top[0][:3]:
            heapq.heapreplace(self._top, entry)

    @property
    def top(self) -> list[ProductRecord]:
        return [e[3] for e in sorted(self._top, key=lambda e: e[:3], reverse=True)]

    def seed(self, resume: ResumeState) -> None:
        self.genders.update(resume.genders)
        self.discount_counts.update(resume.discount_counts)
        for item in resume.top:
            entry = (item.discount_pct, item.savings_minor, item.external_id, item)
            if len(self._top) < TOP_SIZE:
                heapq.heappush(self._top, entry)
            elif entry[:3] > self._top[0][:3]:
                heapq.heapreplace(self._top, entry)
        if self.keep_items and resume.items:
            self.items.update(resume.items)
        for (key, _page), ids in resume.done_pages.items():
            self.per_segment[key].update(ids)


class ScrapeRunner:
    def __init__(
        self,
        adapter: SiteAdapter,
        options: RunOptions | None = None,
        *,
        progress: ProgressListener | None = None,
        sink: RunSink | None = None,
        raw_sink: RawSink | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._adapter = adapter
        self._opts = options or RunOptions()
        self._progress = progress or NullProgress()
        self._sink = sink or NullSink()
        self._raw_sink = raw_sink
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._requests = 0
        self._retries = 0

    @property
    def safe_limit(self) -> int:
        return int(self._adapter.page_size * self._adapter.max_pages * self._opts.safe_limit_ratio)

    async def run(self, resume: ResumeState | None = None) -> ScrapeResult:
        """Scrape the whole catalog, or finish an interrupted run when `resume` is given."""
        started = datetime.now(UTC)
        await self._adapter.warm_up()

        collector = _Collector(keep_items=self._opts.keep_items)
        if resume is None:
            expected_total, plan = await self._plan(collector)
            done: set[tuple[str, int]] = {(sp.segment.key, 1) for sp in plan}
        else:
            expected_total, plan = resume.expected_total, list(resume.plan)
            collector.seed(resume)
            done = set(resume.done_pages)
            log.info("Resuming: %d pages already fetched", len(done))

        jobs = [
            (sp.segment, page)
            for sp in plan
            for page in range(1, sp.pages + 1)
            if (sp.segment.key, page) not in done
        ]
        pages_total = sum(sp.pages for sp in plan)
        pages_done = pages_total - len(jobs)
        self._progress.on_planned(len(plan), pages_total)
        self._progress.on_page(pages_done, len(collector.items))
        log.info(
            "Planned %d segments, %d pages (%d expected items), %d to fetch",
            len(plan),
            pages_total,
            expected_total,
            len(jobs),
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
                gender = self._adapter.gender_of(segment)
                collector.add(segment, gender, result)
                self._sink.on_page(segment, page, gender, result)
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
            expected_total=expected_total,
            item_count=len(collector.genders),
            genders=collector.genders,
            discount_counts=dict(collector.discount_counts),
            top=collector.top,
            items=collector.items if self._opts.keep_items else None,
            segments=[self._report(sp, collector) for sp in plan],
            requests=self._requests,
            retries=self._retries,
            invalid_items=collector.invalid,
            limited=any(sp.limited for sp in plan),
            segment_threshold=self._opts.segment_completeness,
            total_threshold=self._opts.total_completeness,
        )

    async def _plan(self, collector: _Collector) -> tuple[int, list[SegmentPlan]]:
        root = await self._request(Segment(), 1)
        if root.category_tree:
            self._sink.on_category_tree(root.category_tree)
        roots = self._adapter.root_segments(root) or [Segment()]
        planned = await plan_segments(
            self._planning_fetch,
            roots,
            limit=self.safe_limit,
            fallback_price_range=root.facets.price_range,
            known_first_pages={Segment(): root},
        )
        plan = [self._segment_plan(p) for p in planned]
        self._sink.on_plan(root.count, plan)
        for p in planned:  # page 1 of every segment was fetched while planning
            gender = self._adapter.gender_of(p.segment)
            collector.add(p.segment, gender, p.first_page)
            self._sink.on_page(p.segment, 1, gender, p.first_page)
        return root.count, plan

    def _segment_plan(self, planned: PlannedSegment) -> SegmentPlan:
        full = min(
            max(1, math.ceil(planned.count / self._adapter.page_size)), self._adapter.max_pages
        )
        limit = self._opts.max_pages_per_segment
        return SegmentPlan(
            segment=planned.segment,
            count=planned.count,
            pages=min(full, limit) if limit is not None else full,
            full_pages=full,
            truncated=planned.truncated,
        )

    @staticmethod
    def _report(plan: SegmentPlan, collector: _Collector) -> SegmentReport:
        key = plan.segment.key
        return SegmentReport(
            key=key,
            expected=plan.count,
            fetched=len(collector.per_segment[key]),
            pages=plan.pages,
            truncated=plan.truncated,
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
