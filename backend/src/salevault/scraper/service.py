"""A persisted scrape run: lock, stage pages, finalize into the catalog, record the outcome."""

import asyncio
import logging
import random
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import analyze, session_scope
from salevault.db.finalize import RunStats, finalize_run
from salevault.db.runs import DbRunSink, RunRepository
from salevault.scraper.base import SiteAdapter, SiteInfo
from salevault.scraper.errors import ScrapeError
from salevault.scraper.runner import (
    ProgressListener,
    RawSink,
    RunOptions,
    ScrapeResult,
    ScrapeRunner,
    Sleep,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: int
    status: str
    result: ScrapeResult
    stats: RunStats


AdapterOpener = Callable[[], AbstractAsyncContextManager[SiteAdapter]]
"""Opens the adapter (and its browser) only after the run lock is taken."""


async def execute_run(
    open_adapter: AdapterOpener,
    site: SiteInfo,
    factory: sessionmaker[Session],
    *,
    options: RunOptions | None = None,
    trigger: str = "cli",
    resume: bool = False,
    progress: ProgressListener | None = None,
    raw_sink: RawSink | None = None,
    sleep: Sleep = asyncio.sleep,
    rng: random.Random | None = None,
) -> RunOutcome:
    """Run (or resume) a scrape and merge it into the catalog.

    Status: `success` (complete, may deactivate items), `partial` (finished but incomplete:
    merged, nothing deactivated), `failed` / `cancelled` (staging kept for `--resume`).
    """
    repo = RunRepository(factory)
    if resume:
        run_id, state = repo.resume(site, trigger=trigger)
        log.info("Resuming run #%d of %s", run_id, site.code)
    else:
        run_id, state = repo.start(site, trigger=trigger), None
        log.info("Started run #%d of %s", run_id, site.code)

    try:
        async with open_adapter() as adapter:
            runner = ScrapeRunner(
                adapter,
                options,
                progress=progress,
                sink=DbRunSink(factory, run_id),
                raw_sink=raw_sink,
                sleep=sleep,
                rng=rng,
            )
            result = await runner.run(state)
        status = "success" if result.complete else "partial"
        with session_scope(factory) as session:
            stats = finalize_run(session, run_id, deactivate=status == "success")
    except asyncio.CancelledError:
        repo.finish(run_id, "cancelled", error="Cancelled")
        raise
    except ScrapeError as exc:
        repo.finish(run_id, "failed", error=str(exc))
        raise
    except Exception as exc:
        repo.finish(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise

    try:
        analyze(factory)
    except Exception as exc:  # statistics are an optimization, never a reason to fail a run
        log.warning("ANALYZE after run #%d failed: %s", run_id, exc)

    duration = (result.finished_at - result.started_at).total_seconds()
    repo.finish(
        run_id,
        status,
        stats=stats.to_json()
        | {
            "expected": result.expected_total,
            "coverage": round(result.completeness, 4),
            "requests": result.requests,
            "retries": result.retries,
            "duration_s": round(duration, 1),
        },
    )
    return RunOutcome(run_id=run_id, status=status, result=result, stats=stats)
