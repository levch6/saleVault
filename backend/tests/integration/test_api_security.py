"""What a foreign web page, or a malformed request, can and cannot do to the local API."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from salevault.api.app import create_app
from salevault.catalog import queries
from salevault.config import Settings

EVIL = "https://evil.example"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>index</html>")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)")
    app = create_app(Settings(data_dir=tmp_path, frontend_dist=dist))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_unknown_host_names_are_refused(client: TestClient) -> None:
    """DNS rebinding: a page re-points its own domain at 127.0.0.1."""
    assert client.get("/api/health", headers={"Host": "evil.example:8000"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{"Origin": EVIL}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}],
)
def test_writes_from_other_sites_are_refused(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/api/runs/1/cancel", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_writes_from_the_app_itself_pass(client: TestClient) -> None:
    """The Vite dev server on :5173 is the same site."""
    headers = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}

    assert client.post("/api/runs/1/cancel", headers=headers).status_code == 404


def test_security_and_cache_headers(client: TestClient) -> None:
    index = client.get("/")
    asset = client.get("/assets/app-1a2b.js")

    assert index.headers["x-content-type-options"] == "nosniff"
    assert index.headers["referrer-policy"] == "no-referrer"
    assert index.headers["cache-control"] == "no-cache"
    assert "immutable" in asset.headers["cache-control"]


def test_the_ui_gets_a_strict_script_policy(client: TestClient) -> None:
    policy = client.get("/").headers["content-security-policy"]
    directives = {
        name: sources.split() for name, sources in (d.split(" ", 1) for d in policy.split("; "))
    }

    assert directives["script-src"] == ["'self'"]
    assert directives["img-src"] == ["'self'", "data:", "https://img2.ans-media.com"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert "content-security-policy" not in client.get("/api/docs").headers, "Swagger uses a CDN"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/products/" + "9" * 25),
        ("GET", "/api/products?brand=" + "9" * 25),
        ("GET", "/api/products?price_min=" + "9" * 25),
        ("GET", "/api/products?page=" + "9" * 18),
        ("PUT", "/api/favorites/" + "9" * 25),
        ("GET", "/api/runs/" + "9" * 25),
    ],
)
def test_huge_numbers_are_validation_errors(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 422


def test_a_nul_byte_in_the_path_serves_the_app(client: TestClient) -> None:
    response = client.get("/%00")

    assert response.status_code == 200
    assert "index" in response.text


def test_unexpected_errors_are_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(queries, "list_favorites", broken)

    response = client.get("/api/favorites")

    assert response.status_code == 500
    assert response.json()["code"] == "internal"


def test_a_busy_database_is_a_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def locked(*_args: object) -> None:
        raise OperationalError("INSERT ...", {}, Exception("database is locked"))

    monkeypatch.setattr(queries, "list_favorites", locked)

    response = client.get("/api/favorites")

    assert response.status_code == 503
    assert response.json()["code"] == "database_busy"
