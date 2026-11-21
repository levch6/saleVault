import json
import subprocess
import sys
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import session_scope
from salevault.db.models import RunItem, ScrapeRun, Site
from salevault.db.runs import (
    DbRunSink,
    NothingToResumeError,
    RunAlreadyRunningError,
    RunRepository,
)
from salevault.db.types import utcnow
from salevault.domain.models import Gender
from salevault.scraper.base import Facets, PageResult, Segment
from salevault.scraper.runner import SegmentPlan
from tests.fakes import FAKE_SITE, FakeItem, make_record


def dead_pid() -> int:
    proc = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(proc.stdout)


def test_start_registers_the_site_and_a_running_run(factory: sessionmaker[Session]) -> None:
    run_id = RunRepository(factory).start(FAKE_SITE, trigger="ui")

    with session_scope(factory) as session:
        run = session.get_one(ScrapeRun, run_id)
        site = session.get_one(Site, run.site_id)
        assert (run.status, run.trigger, site.code, site.currency) == (
            "running",
            "ui",
            "fake",
            "UAH",
        )


def test_only_one_live_run_per_site(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    repo.start(FAKE_SITE, trigger="cli")  # pid = this test process, alive

    with pytest.raises(RunAlreadyRunningError):
        repo.start(FAKE_SITE, trigger="cli")


def test_dead_process_runs_are_reaped(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    zombie = repo.start(FAKE_SITE, trigger="cli", pid=dead_pid())

    fresh = repo.start(FAKE_SITE, trigger="cli")

    assert fresh != zombie
    row = repo.get(zombie)
    assert row.status == "failed"
    assert row.error is not None


def test_stale_heartbeat_runs_are_reaped(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    stuck = repo.start(FAKE_SITE, trigger="cli")
    with session_scope(factory) as session:
        session.get_one(ScrapeRun, stuck).updated_at = utcnow() - timedelta(hours=1)

    repo.start(FAKE_SITE, trigger="cli")

    assert repo.get(stuck).status == "failed"


def test_resume_requires_an_interrupted_run(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    with pytest.raises(NothingToResumeError):
        repo.resume(FAKE_SITE, trigger="cli")

    run_id = repo.start(FAKE_SITE, trigger="cli")
    repo.finish(run_id, "success")
    with pytest.raises(NothingToResumeError):
        repo.resume(FAKE_SITE, trigger="cli")


def test_resume_loads_plan_pages_and_items(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    run_id = repo.start(FAKE_SITE, trigger="cli")
    sink = DbRunSink(factory, run_id)
    plan = [SegmentPlan(Segment(sex="M", price=(0, 99)), count=3, pages=2, full_pages=2)]
    sink.on_plan(3, plan)
    records = (
        make_record(FakeItem("a", frozenset({"M"}), 10)),
        make_record(FakeItem("b", frozenset({"M"}), 20)),
    )
    sink.on_page(
        plan[0].segment,
        1,
        Gender.MEN,
        PageResult(count=3, items=records, facets=Facets(), raw="{}"),
    )
    repo.finish(run_id, "failed", error="boom")

    resumed_id, state = repo.resume(FAKE_SITE, trigger="ui")

    assert resumed_id == run_id
    assert state.expected_total == 3
    assert state.plan == tuple(plan)
    assert dict(state.done_pages) == {("sex=M;price=0-99", 1): ("a", "b")}
    assert state.items is not None
    assert set(state.items) == {"a", "b"}
    assert set(state.genders) == {"a", "b"}
    assert sum(state.discount_counts.values()) == 2
    assert [p.external_id for p in state.top] == ["b", "a"]  # same %, b saves more
    assert state.genders["a"] == Gender.MEN
    row = repo.get(run_id)
    assert (row.status, row.trigger, row.error, row.pages_done, row.items_seen) == (
        "running",
        "ui",
        None,
        1,
        2,
    )


def test_a_new_run_discards_unresumed_staging(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    old = repo.start(FAKE_SITE, trigger="cli")
    record = make_record(FakeItem("a", frozenset({"M"}), 10))
    DbRunSink(factory, old).on_page(
        Segment(), 1, Gender.MEN, PageResult(count=1, items=(record,), facets=Facets(), raw="{}")
    )
    repo.finish(old, "cancelled")

    repo.start(FAKE_SITE, trigger="cli")

    with session_scope(factory) as session:
        assert session.scalar(select(func.count()).select_from(RunItem)) == 0


def test_list_runs_newest_first_with_stats(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    first = repo.start(FAKE_SITE, trigger="cli")
    repo.finish(first, "success", stats={"new": 5})
    second = repo.start(FAKE_SITE, trigger="ui")
    repo.finish(second, "partial", stats={"new": 1})

    rows = repo.list_runs(site="fake")

    assert [r.id for r in rows] == [second, first]
    assert rows[1].stats == {"new": 5}
    assert repo.list_runs(site="other") == []
    assert json.dumps(rows[0].stats) == '{"new": 1}'


def test_planning_keeps_the_heartbeat_fresh(factory: sessionmaker[Session]) -> None:
    repo = RunRepository(factory)
    run_id = repo.start(FAKE_SITE, trigger="cli")
    with session_scope(factory) as session:
        session.get_one(ScrapeRun, run_id).updated_at = utcnow() - timedelta(minutes=10)

    DbRunSink(factory, run_id).on_heartbeat()

    with session_scope(factory) as session:
        assert utcnow() - session.get_one(ScrapeRun, run_id).updated_at < timedelta(minutes=1)
