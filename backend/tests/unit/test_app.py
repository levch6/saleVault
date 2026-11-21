from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from salevault import __version__
from salevault.api.app import create_app
from salevault.config import Settings


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    return TestClient(create_app(settings))


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("secret")
    return dist


def test_health(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_openapi_uses_short_operation_ids(tmp_path: Path) -> None:
    schema = make_client(tmp_path).get("/api/openapi.json").json()

    assert schema["paths"]["/api/health"]["get"]["operationId"] == "get_health"


def test_without_built_frontend_root_is_404(tmp_path: Path) -> None:
    assert make_client(tmp_path).get("/").status_code == 404


@pytest.mark.usefixtures("dist")
def test_spa_routes_fall_back_to_index(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    for path in ("/", "/favorites", "/runs?site=prm"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == "<html>spa</html>"


@pytest.mark.usefixtures("dist")
def test_static_files_are_served(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.usefixtures("dist")
def test_unknown_api_route_is_404_not_spa(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    assert client.get("/api/nope").status_code == 404
    assert client.get("/api").status_code == 404


@pytest.mark.usefixtures("dist")
def test_path_traversal_does_not_escape_dist(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/..%2Fsecret.txt")

    assert "secret" not in response.text
