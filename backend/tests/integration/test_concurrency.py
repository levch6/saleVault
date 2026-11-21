"""Several connections and processes on one database file: what the API and two scrapers do."""

import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from salevault.api.app import create_app
from salevault.api.launcher import RunLauncher, RunNotRunningError
from salevault.catalog import queries
from salevault.config import Settings
from salevault.db.engine import create_db_engine, make_session_factory, session_scope, sqlite_url
from salevault.db.migrate import downgrade, upgrade
from salevault.db.models import Product, ScrapeRun
from salevault.db.runs import DbRunSink, RunRepository, process_start
from salevault.domain.models import Gender
from salevault.scraper import service
from salevault.scraper.base import Facets, PageResult, Segment
from tests.fakes import FAKE_SITE, FakeAdapter, make_catalog, opener
from tests.integration.helpers import product, seed_run
from tests.integration.test_runs_repo import dead_pid


@pytest.fixture
def writer(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine, write=True)


def db_file(engine: Engine) -> Path:
    assert engine.url.database is not None
    return Path(engine.url.database)


def test_concurrent_writers_wait_for_each_other(
    engine: Engine, writer: sessionmaker[Session]
) -> None:
    """Read, someone else writes, then write: a deferred transaction failed here at once."""
    seed_run(writer, FAKE_SITE, [(Gender.MEN, [product("x", 100, regular=200)])])
    errors: list[Exception] = []

    def other_writer() -> None:
        try:
            other = sqlite3.connect(db_file(engine), timeout=10, isolation_level=None)
            other.execute("UPDATE scrape_runs SET items_seen = items_seen + 1")
            other.close()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=other_writer)
    with session_scope(writer) as session:
        product_id = session.scalars(select(Product.id)).one()
        thread.start()
        time.sleep(0.2)
        assert queries.add_favorite(session, product_id, None)
    thread.join()

    assert errors == []


def test_staging_waits_for_a_long_write_lock(engine: Engine, writer: sessionmaker[Session]) -> None:
    """Another shop's merge holds the write lock for a while; this scraper's page must wait."""
    run_id = RunRepository(writer).start(FAKE_SITE, trigger="ui")
    released = threading.Event()

    def hold_lock() -> None:
        holder = sqlite3.connect(db_file(engine), isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE scrape_runs SET items_seen = items_seen")
        time.sleep(1.5)
        holder.execute("COMMIT")
        holder.close()
        released.set()

    thread = threading.Thread(target=hold_lock)
    thread.start()
    time.sleep(0.2)
    page = PageResult(count=1, items=(product("p", 10, regular=20),), facets=Facets(), raw="{}")
    DbRunSink(writer, run_id).on_page(Segment(), 1, Gender.MEN, page)
    thread.join()

    assert released.is_set()
    assert RunRepository(writer).get(run_id).items_seen == 1


async def test_merge_and_outcome_commit_together(
    writer: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def analyze_after_merge(factory: sessionmaker[Session]) -> None:
        with session_scope(factory) as session:
            seen.extend(session.scalars(select(ScrapeRun.status)))

    monkeypatch.setattr(service, "analyze", analyze_after_merge)
    adapter = FakeAdapter(make_catalog({"M": 30}))

    outcome = await service.execute_run(opener(adapter), FAKE_SITE, writer, sleep=no_sleep)

    assert seen == ["success"], "the run is recorded before any housekeeping"
    with session_scope(writer) as session:
        run = session.get_one(ScrapeRun, outcome.run_id)
        assert run.category_tree_json is None, "the merged tree is not kept"
        assert run.stats_json is not None
        assert '"invalid_items": 0' in run.stats_json


async def no_sleep(_seconds: float) -> None:
    return None


def test_the_database_allows_one_running_run_per_site(writer: sessionmaker[Session]) -> None:
    RunRepository(writer).start(FAKE_SITE, trigger="cli")

    with session_scope(writer) as session:
        site_id = session.scalars(select(ScrapeRun.site_id)).one()
    second = ScrapeRun(site_id=site_id, trigger="cli", status="running")

    with pytest.raises(IntegrityError), session_scope(writer) as session:
        session.add(second)


def test_runs_record_the_start_time_of_their_process(writer: sessionmaker[Session]) -> None:
    repo = RunRepository(writer)
    run_id = repo.start(FAKE_SITE, trigger="cli")

    assert repo.pid_of(run_id) == (os.getpid(), process_start(os.getpid()))


def test_cancel_never_signals_a_reused_pid(tmp_path: Path, writer: sessionmaker[Session]) -> None:
    """The scraper died; its pid now belongs to an unrelated process."""
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        repo = RunRepository(writer)
        run_id = repo.start(FAKE_SITE, trigger="ui", pid=bystander.pid)
        with session_scope(writer) as session:
            session.execute(
                text("UPDATE scrape_runs SET pid_start = 1 WHERE id = :id"), {"id": run_id}
            )

        with pytest.raises(RunNotRunningError):
            RunLauncher(repo, data_dir=tmp_path).cancel(run_id)

        assert bystander.poll() is None, "the unrelated process is still alive"
        assert repo.get(run_id).status == "failed"
    finally:
        bystander.kill()
        bystander.wait()


def test_dead_runs_show_as_failed_without_a_new_run(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, frontend_dist=tmp_path / "dist"))
    with TestClient(app) as client:
        factory: sessionmaker[Session] = client.app.state.write_factory  # type: ignore[attr-defined]
        RunRepository(factory).start(FAKE_SITE, trigger="ui", pid=dead_pid())

        sites = {s["code"]: s for s in client.get("/api/sites").json()}

        assert sites[FAKE_SITE.code]["latest"]["status"] == "failed"


def test_existing_databases_are_backed_up_before_migrating(tmp_path: Path) -> None:
    engine = create_db_engine(sqlite_url(tmp_path / "salevault.db"))
    upgrade(engine)
    assert not (tmp_path / "backups").exists(), "a fresh database needs no backup"

    downgrade(engine, "8b45b97da1bc")
    upgrade(engine)

    assert len(list((tmp_path / "backups").glob("salevault-*.db"))) == 1
    engine.dispose()
