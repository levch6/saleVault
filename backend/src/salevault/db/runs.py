"""Run lifecycle persistence: locking, progress, staging of fetched pages, resume state."""

import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import session_scope
from salevault.db.models import RunItem, RunPage, ScrapeRun, Site
from salevault.db.types import utcnow
from salevault.domain.models import CategoryNode, Gender, ProductRecord
from salevault.scraper.base import PageResult, Segment, SiteInfo
from salevault.scraper.runner import TOP_SIZE, ResumeState, SegmentPlan

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)
"""A running run without a heartbeat for this long is considered dead."""


class RunAlreadyRunningError(Exception):
    pass


class NothingToResumeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunRow:
    id: int
    site: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    expected_total: int | None
    pages_total: int | None
    pages_done: int
    items_seen: int
    stats: Mapping[str, object] | None
    error: str | None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def start(self, site: SiteInfo, *, trigger: str, pid: int | None = None) -> int:
        """Create a new running run; refuses if another run of the site is alive."""
        with session_scope(self._factory) as session:
            site_row = _ensure_site(session, site)
            self._check_not_running(session, site_row)
            # Older unfinished runs can no longer be resumed once a new run starts.
            stale = select(ScrapeRun.id).where(
                ScrapeRun.site_id == site_row.id, ScrapeRun.status.in_(("failed", "cancelled"))
            )
            session.execute(delete(RunItem).where(RunItem.run_id.in_(stale)))
            session.execute(delete(RunPage).where(RunPage.run_id.in_(stale)))
            run = ScrapeRun(
                site_id=site_row.id, trigger=trigger, pid=pid or os.getpid(), status="running"
            )
            session.add(run)
            session.flush()
            return run.id

    def resume(
        self, site: SiteInfo, *, trigger: str, pid: int | None = None, with_items: bool = True
    ) -> tuple[int, ResumeState]:
        """Reopen the site's latest failed or cancelled run and load what it already has."""
        with session_scope(self._factory) as session:
            site_row = _ensure_site(session, site)
            self._check_not_running(session, site_row)
            run = session.scalars(
                select(ScrapeRun)
                .where(ScrapeRun.site_id == site_row.id)
                .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
                .limit(1)
            ).first()
            if run is None or run.status not in ("failed", "cancelled") or not run.segments_json:
                raise NothingToResumeError(
                    f"No interrupted run of {site.code} to resume; start a new one instead"
                )
            state = _load_resume_state(session, run, with_items=with_items)
            run.status = "running"
            run.trigger = trigger
            run.pid = pid or os.getpid()
            run.error = None
            run.finished_at = None
            run.updated_at = utcnow()
            return run.id, state

    def finish(
        self,
        run_id: int,
        status: str,
        *,
        error: str | None = None,
        stats: Mapping[str, object] | None = None,
    ) -> None:
        with session_scope(self._factory) as session:
            run = session.get_one(ScrapeRun, run_id)
            now = utcnow()
            run.status = status
            run.finished_at = now
            run.updated_at = now
            run.error = error
            if stats is not None:
                run.stats_json = json.dumps(dict(stats))

    def list_runs(self, *, site: str | None = None, limit: int = 20) -> list[RunRow]:
        with session_scope(self._factory) as session:
            query = (
                select(ScrapeRun, Site.code)
                .join(Site, Site.id == ScrapeRun.site_id)
                .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
                .limit(limit)
            )
            if site is not None:
                query = query.where(Site.code == site)
            return [_row(run, code) for run, code in session.execute(query)]

    def active_run(self, site_code: str) -> RunRow | None:
        """The site's live running run, after reaping dead ones; None if the site is idle."""
        with session_scope(self._factory) as session:
            site = session.scalars(select(Site).where(Site.code == site_code)).first()
            if site is None:
                return None
            try:
                self._check_not_running(session, site)
            except RunAlreadyRunningError:
                run = session.scalars(
                    select(ScrapeRun).where(
                        ScrapeRun.site_id == site.id, ScrapeRun.status == "running"
                    )
                ).one()
                return _row(run, site.code)
            return None

    def run_id_for_pid(self, pid: int) -> int | None:
        with session_scope(self._factory) as session:
            return session.scalar(
                select(ScrapeRun.id)
                .where(ScrapeRun.pid == pid, ScrapeRun.status == "running")
                .order_by(ScrapeRun.id.desc())
                .limit(1)
            )

    def pid_of(self, run_id: int) -> int | None:
        with session_scope(self._factory) as session:
            return session.scalar(select(ScrapeRun.pid).where(ScrapeRun.id == run_id))

    def find(self, run_id: int) -> RunRow | None:
        with session_scope(self._factory) as session:
            run = session.get(ScrapeRun, run_id)
            if run is None:
                return None
            return _row(run, session.get_one(Site, run.site_id).code)

    def get(self, run_id: int) -> RunRow:
        with session_scope(self._factory) as session:
            run = session.get_one(ScrapeRun, run_id)
            code = session.get_one(Site, run.site_id).code
            return _row(run, code)

    def _check_not_running(self, session: Session, site: Site) -> None:
        for run in session.scalars(
            select(ScrapeRun).where(ScrapeRun.site_id == site.id, ScrapeRun.status == "running")
        ):
            stale = utcnow() - run.updated_at > STALE_AFTER
            if run.pid is not None and pid_alive(run.pid) and not stale:
                raise RunAlreadyRunningError(
                    f"Run #{run.id} of {site.code} is still running (pid {run.pid})"
                )
            log.warning(
                "Run #%d of %s died without finishing; marking it failed", run.id, site.code
            )
            run.status = "failed"
            run.finished_at = utcnow()
            run.error = "The scraper process ended unexpectedly"


class DbRunSink:
    """Stages the plan and every fetched page in the DB, so a run survives crashes."""

    def __init__(self, factory: sessionmaker[Session], run_id: int) -> None:
        self._factory = factory
        self._run_id = run_id
        # Progress counters live in memory (a COUNT per page grows with the staging table);
        # a resumed run starts from what is already staged.
        with session_scope(factory) as session:
            self._pages = {
                (key, page)
                for key, page in session.execute(
                    select(RunPage.segment_key, RunPage.page).where(RunPage.run_id == run_id)
                )
            }
            self._items = set(
                session.scalars(select(RunItem.external_id).where(RunItem.run_id == run_id))
            )

    def on_plan(self, expected_total: int, plan: Sequence[SegmentPlan]) -> None:
        with session_scope(self._factory) as session:
            run = session.get_one(ScrapeRun, self._run_id)
            run.expected_total = expected_total
            run.segments_json = json.dumps([p.to_json() for p in plan])
            run.pages_total = sum(p.pages for p in plan)
            run.updated_at = utcnow()

    def on_category_tree(self, nodes: Sequence[CategoryNode]) -> None:
        with session_scope(self._factory) as session:
            run = session.get_one(ScrapeRun, self._run_id)
            run.category_tree_json = json.dumps([n.model_dump() for n in nodes])

    def on_page(self, segment: Segment, page: int, gender: Gender, result: PageResult) -> None:
        with session_scope(self._factory) as session:
            if result.items:
                stmt = sqlite_insert(RunItem).values(
                    [
                        {
                            "run_id": self._run_id,
                            "external_id": item.external_id,
                            "gender_mask": int(gender),
                            "record_json": item.model_dump_json(),
                        }
                        for item in result.items
                    ]
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[RunItem.run_id, RunItem.external_id],
                    set_={
                        "gender_mask": RunItem.__table__.c.gender_mask.op("|")(
                            stmt.excluded.gender_mask
                        ),
                        "record_json": stmt.excluded.record_json,
                    },
                )
                session.execute(stmt)
            session.merge(
                RunPage(
                    run_id=self._run_id,
                    segment_key=segment.key,
                    page=page,
                    items_count=len(result.items),
                    item_ids_json=json.dumps([i.external_id for i in result.items]),
                    fetched_at=utcnow(),
                )
            )
            self._pages.add((segment.key, page))
            self._items.update(i.external_id for i in result.items)
            run = session.get_one(ScrapeRun, self._run_id)
            run.pages_done = len(self._pages)
            run.items_seen = len(self._items)
            run.updated_at = utcnow()


def _ensure_site(session: Session, info: SiteInfo) -> Site:
    site = session.scalars(select(Site).where(Site.code == info.code)).first()
    if site is None:
        site = Site(code=info.code, name=info.name, origin=info.origin, currency=info.currency)
        session.add(site)
        session.flush()
    else:
        site.name, site.origin, site.currency = info.name, info.origin, info.currency
    return site


def _load_resume_state(session: Session, run: ScrapeRun, *, with_items: bool) -> ResumeState:
    """Rebuild a run's progress from staging; summaries come from SQL so that resuming a
    140k-item run does not parse every staged record."""
    plan = tuple(SegmentPlan.from_json(d) for d in json.loads(run.segments_json or "[]"))
    done = {
        (p.segment_key, p.page): tuple(json.loads(p.item_ids_json))
        for p in session.scalars(select(RunPage).where(RunPage.run_id == run.id))
    }
    of_run = RunItem.run_id == run.id
    genders = {
        external_id: Gender(mask)
        for external_id, mask in session.execute(
            select(RunItem.external_id, RunItem.gender_mask).where(of_run)
        )
    }
    discount = func.json_extract(RunItem.record_json, "$.discount_pct")
    savings = func.json_extract(RunItem.record_json, "$.savings_minor")
    discount_counts = {
        int(pct): n
        for pct, n in session.execute(
            select(discount, func.count()).where(of_run).group_by(discount)
        )
        if pct is not None
    }
    top = [
        ProductRecord.model_validate_json(record_json)
        for record_json in session.scalars(
            select(RunItem.record_json)
            .where(of_run)
            .order_by(discount.desc(), savings.desc(), RunItem.external_id.desc())
            .limit(TOP_SIZE)
        )
    ]
    items = (
        {
            external_id: ProductRecord.model_validate_json(record_json)
            for external_id, record_json in session.execute(
                select(RunItem.external_id, RunItem.record_json).where(of_run)
            )
        }
        if with_items
        else None
    )
    return ResumeState(
        expected_total=run.expected_total or 0,
        plan=plan,
        done_pages=done,
        genders=genders,
        discount_counts=discount_counts,
        top=top,
        items=items,
    )


def _row(run: ScrapeRun, site_code: str) -> RunRow:
    return RunRow(
        id=run.id,
        site=site_code,
        status=run.status,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        expected_total=run.expected_total,
        pages_total=run.pages_total,
        pages_done=run.pages_done,
        items_seen=run.items_seen,
        stats=json.loads(run.stats_json) if run.stats_json else None,
        error=run.error,
    )
