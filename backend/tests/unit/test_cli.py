import json
from pathlib import Path

from typer.testing import CliRunner

from salevault import __version__
from salevault.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_openapi_export(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"

    result = runner.invoke(app, ["openapi", "--out", str(out)])

    assert result.exit_code == 0, result.output
    schema = json.loads(out.read_text())
    assert "/api/health" in schema["paths"]
