import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from salevault import __version__
from salevault.cli import app
from salevault.config import get_settings

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(result: Result) -> str:
    """Output without styling or line wrapping (Typer forces colors when GITHUB_ACTIONS is set)."""
    return " ".join(ANSI.sub("", result.output).split())


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the app's data directory (DB, browser profiles) at a temp folder."""
    monkeypatch.setenv("SALEVAULT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_scrape_rejects_unknown_sites() -> None:
    result = runner.invoke(app, ["scrape", "nope", "--dry-run"])

    assert result.exit_code == 2
    assert "Unknown site" in plain(result)


def test_resume_cannot_be_a_dry_run() -> None:
    result = runner.invoke(app, ["scrape", "prm", "--dry-run", "--resume"])

    assert result.exit_code == 2
    assert "--resume" in plain(result)


def test_db_upgrade_creates_the_database(data_dir: Path) -> None:
    result = runner.invoke(app, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    assert (data_dir / "salevault.db").is_file()
    assert "is at revision" in plain(result)


def test_runs_on_an_empty_database(data_dir: Path) -> None:
    result = runner.invoke(app, ["runs"])

    assert result.exit_code == 0, result.output
    assert "No runs yet" in plain(result)


def test_openapi_export(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"

    result = runner.invoke(app, ["openapi", "--out", str(out)])

    assert result.exit_code == 0, result.output
    schema = json.loads(out.read_text())
    assert "/api/health" in schema["paths"]


@pytest.mark.parametrize(
    ("container", "expected"),
    [(None, "exposes an API without authentication"), ("1", "publish it on 127.0.0.1 only")],
)
def test_serve_warns_about_a_public_bind(
    monkeypatch: pytest.MonkeyPatch, container: str | None, expected: str
) -> None:
    started: list[str] = []
    monkeypatch.setattr("salevault.cli.uvicorn.run", lambda *_a, **kw: started.append(kw["host"]))
    if container is None:
        monkeypatch.delenv("SALEVAULT_CONTAINER", raising=False)
    else:
        monkeypatch.setenv("SALEVAULT_CONTAINER", container)

    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])  # noqa: S104 (the point of the test)

    assert result.exit_code == 0, result.output
    assert expected in " ".join(plain(result).split())
    assert started == ["0.0.0.0"]  # noqa: S104
