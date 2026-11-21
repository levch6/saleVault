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
from salevault.domain.models import Gender, ProductRecord
from salevault.scraper.base import PageResult, Segment, SiteInfo
from salevault.scraper.runner import ResumeState, SegmentPlan

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
        self, site: SiteInfo, *, trigger: str, pid: int | None = None
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
            state = _load_resume_state(session, run)
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

    def on_plan(self, expected_total: int, plan: Sequence[SegmentPlan]) -> None:
        with session_scope(self._factory) as session:
            run = session.get_one(ScrapeRun, self._run_id)
            run.expected_total = expected_total
            run.segments_json = json.dumps([p.to_json() for p in plan])
            run.pages_total = sum(p.pages for p in plan)
            run.updated_at = utcnow()

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
            run = session.get_one(ScrapeRun, self._run_id)
            run.pages_done = _count(session, RunPage, self._run_id)
            run.items_seen = _count(session, RunItem, self._run_id)
            run.updated_at = utcnow()


def _count(session: Session, model: type[RunPage] | type[RunItem], run_id: int) -> int:
    return (
        session.scalar(select(func.count()).select_from(model).where(model.run_id == run_id)) or 0
    )


def _ensure_site(session: Session, info: SiteInfo) -> Site:
    site = session.scalars(select(Site).where(Site.code == info.code)).first()
    if site is None:
        site = Site(code=info.code, name=info.name, origin=info.origin, currency=info.currency)
        session.add(site)
        session.flush()
    else:
        site.name, site.origin, site.currency = info.name, info.origin, info.currency
    return site


def _load_resume_state(session: Session, run: ScrapeRun) -> ResumeState:
    plan = tuple(SegmentPlan.from_json(d) for d in json.loads(run.segments_json or "[]"))
    done = {
        (p.segment_key, p.page): tuple(json.loads(p.item_ids_json))
        for p in session.scalars(select(RunPage).where(RunPage.run_id == run.id))
    }
    items: dict[str, ProductRecord] = {}
    genders: dict[str, Gender] = {}
    rows = session.execute(
        select(RunItem.external_id, RunItem.gender_mask, RunItem.record_json).where(
            RunItem.run_id == run.id
        )
    )
    for external_id, mask, record_json in rows:
        items[external_id] = ProductRecord.model_validate_json(record_json)
        genders[external_id] = Gender(mask)
    return ResumeState(
        expected_total=run.expected_total or 0,
        plan=plan,
        done_pages=done,
        items=items,
        genders=genders,
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
