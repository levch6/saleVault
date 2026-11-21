import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from salevault.api.app import create_app
from salevault.api.launcher import CommandFactory, scrape_command
from salevault.config import Settings
from salevault.db.runs import DbRunSink, RunRepository
from salevault.domain.models import Gender
from salevault.scraper.base import Facets, PageResult, Segment
from salevault.scraper.runner import SegmentPlan
from salevault.scraper.sites.registry import PRM
from tests.integration.helpers import product, seed_run

# Stands in for `python -m salevault scrape`: registers a running run in the same DB
# (the launcher passes SALEVAULT_DATA_DIR), then waits; SIGTERM finishes it as cancelled.
FAKE_SCRAPER = """
import signal, sys, time
from salevault.config import get_settings
from salevault.db.engine import create_db_engine, make_session_factory, sqlite_url
from salevault.db.runs import RunRepository
from salevault.scraper.sites.registry import PRM

repo = RunRepository(make_session_factory(create_db_engine(sqlite_url(get_settings().db_path))))
run_id = repo.start(PRM.site_info, trigger="ui")

def stop(*_):
    repo.finish(run_id, "cancelled", error="Cancelled")
    sys.exit(143)

signal.signal(signal.SIGTERM, stop)
time.sleep(30)
repo.finish(run_id, "success")
"""


# Like FAKE_SCRAPER, but continues the latest interrupted run the way `--resume` does.
FAKE_RESUMER = FAKE_SCRAPER.replace(
    'run_id = repo.start(PRM.site_info, trigger="ui")',
    'run_id, _state = repo.resume(PRM.site_info, trigger="ui")',
)
launched: list[list[str]] = []


def fake_scraper(site: str, headed: bool | None, resume: bool = False) -> list[str]:
    launched.append(scrape_command(site, headed, resume))
    return [sys.executable, "-c", FAKE_RESUMER if resume else FAKE_SCRAPER]


def crashing_scraper(_site: str, _headed: bool | None, _resume: bool = False) -> list[str]:
    return [sys.executable, "-c", "import sys; print('boom: no browser'); sys.exit(3)"]


def make_client(tmp_path: Path, command: CommandFactory) -> TestClient:
    app = create_app(
        Settings(data_dir=tmp_path, frontend_dist=tmp_path / "dist"),
        scrape_command_factory=command,
    )
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path, fake_scraper) as test_client:
        yield test_client


def wait_for_status(client: TestClient, run_id: int, status: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == status:
            return
        time.sleep(0.1)
    pytest.fail(f"run {run_id} never reached {status}")


def test_sites_list_known_shops_before_any_run(client: TestClient) -> None:
    sites = client.get("/api/sites").json()

    assert [s["code"] for s in sites] == ["answear_ua", "prm"]
    prm = next(s for s in sites if s["code"] == "prm")
    assert prm == {
        "code": "prm",
        "name": "PRM",
        "origin": "https://prm.com",
        "active_products": 0,
        "last_completed": None,
        "latest": None,
        "resumable": False,
    }


def test_sites_show_catalog_size_and_runs(client: TestClient) -> None:
    factory: sessionmaker[Session] = client.app.state.factory  # type: ignore[attr-defined]
    run_id = seed_run(factory, PRM.site_info, [(Gender.MEN, [product("a", 1, regular=2)])])

    site = next(s for s in client.get("/api/sites").json() if s["code"] == "prm")

    assert site["active_products"] == 1
    assert site["last_completed"]["id"] == run_id
    assert site["latest"]["status"] == "success"
    assert client.get("/api/runs").json()[0]["stats"]["new"] == 1
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "success"
    assert client.get("/api/runs/999").status_code == 404


def test_start_poll_and_cancel_a_run(client: TestClient) -> None:
    response = client.post("/api/runs", json={"site": "prm"})

    assert response.status_code == 202, response.text
    (run_id,) = response.json()["run_ids"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert (run["status"], run["trigger"]) == ("running", "ui")

    again = client.post("/api/runs", json={"site": "prm"})
    assert again.status_code == 409
    assert again.json()["code"] == "run_already_running"

    cancel = client.post(f"/api/runs/{run_id}/cancel")
    assert cancel.status_code == 202
    wait_for_status(client, run_id, "cancelled")

    not_running = client.post(f"/api/runs/{run_id}/cancel")
    assert not_running.status_code == 409
    assert not_running.json()["code"] == "run_not_running"
    assert client.post("/api/runs/999/cancel").status_code == 404


def test_unknown_site_is_rejected(client: TestClient) -> None:
    response = client.post("/api/runs", json={"site": "nope"})

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_site"


def test_a_crashing_scraper_reports_its_output(tmp_path: Path) -> None:
    with make_client(tmp_path, crashing_scraper) as client:
        response = client.post("/api/runs", json={"site": "prm"})

    assert response.status_code == 500
    assert response.json()["code"] == "launch_failed"
    assert "boom: no browser" in response.json()["detail"]
    assert list((tmp_path / "logs").glob("run-prm-*.log"))


def test_default_command_runs_the_cli_in_ui_mode() -> None:
    assert scrape_command("prm", None)[1:] == [
        "-m",
        "salevault",
        "scrape",
        "prm",
        "--trigger",
        "ui",
        "--top",
        "0",
    ]
    assert scrape_command("prm", True)[-1] == "--headed"
    assert scrape_command("prm", False)[-1] == "--headless"


def interrupted_run(client: TestClient) -> int:
    """A cancelled PRM run that kept its plan and one staged page, like a Cancel in the UI."""
    factory: sessionmaker[Session] = client.app.state.write_factory  # type: ignore[attr-defined]
    repo = RunRepository(factory)
    run_id = repo.start(PRM.site_info, trigger="ui")
    plan = [SegmentPlan(segment=Segment(), count=100, pages=2, full_pages=2, truncated=False)]
    sink = DbRunSink(factory, run_id)
    sink.on_plan(100, plan)
    page = PageResult(count=100, items=(product("a", 10, regular=20),), facets=Facets(), raw="{}")
    sink.on_page(Segment(), 1, Gender.MEN, page)
    repo.finish(run_id, "cancelled", error="Cancelled")
    return run_id


def test_an_interrupted_run_can_be_resumed_from_the_app(client: TestClient) -> None:
    run_id = interrupted_run(client)
    sites = {s["code"]: s for s in client.get("/api/sites").json()}
    assert sites["prm"]["resumable"] is True
    launched.clear()

    response = client.post("/api/runs", json={"site": "prm", "resume": True})

    assert response.status_code == 202, response.text
    assert response.json()["run_ids"] == [run_id], "the same run goes on"
    assert "--resume" in launched[0]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
    client.post(f"/api/runs/{run_id}/cancel")
    wait_for_status(client, run_id, "cancelled")


def test_resume_needs_an_interrupted_run_and_one_site(client: TestClient) -> None:
    nothing = client.post("/api/runs", json={"site": "prm", "resume": True})
    every = client.post("/api/runs", json={"site": "all", "resume": True})

    assert (nothing.status_code, nothing.json()["code"]) == (409, "nothing_to_resume")
    assert (every.status_code, every.json()["code"]) == (422, "resume_needs_one_site")
