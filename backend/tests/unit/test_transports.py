from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from salevault.scraper import transports
from salevault.scraper.base import HttpResponse
from salevault.scraper.errors import BlockedError, ScrapeError
from salevault.scraper.sites.answear_platform import TransportMode

opened: list[str] = []
UNUSED_PROFILE = Path("never-created")  # the fakes never touch it


class FakeHttp:
    status = 200
    opens = 0

    def __init__(self, origin: str) -> None:
        self.origin = origin

    async def __aenter__(self) -> Self:
        opened.append("http")
        return self

    async def __aexit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        opened.append("http closed")

    async def open(self, url: str) -> int:
        FakeHttp.opens += 1
        return self.status

    async def post_json(self, path: str, body: object, headers: object) -> HttpResponse:
        return HttpResponse(200, "{}")


class FakeBrowser(FakeHttp):
    def __init__(self, profile_dir: Path, *, headless: bool) -> None:
        super().__init__("browser")

    async def __aenter__(self) -> Self:
        opened.append("browser")
        return self


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    opened.clear()
    FakeHttp.status = 200
    FakeHttp.opens = 0
    monkeypatch.setattr(transports, "HttpSession", FakeHttp)
    monkeypatch.setattr(transports, "BrowserSession", FakeBrowser)


async def use(mode: TransportMode) -> str:
    async with transports.open_adapter(
        "prm", transport=mode, headless=False, profile_dir=UNUSED_PROFILE
    ) as adapter:
        return type(adapter._transport).__name__


async def test_auto_prefers_http() -> None:
    assert await use("auto") == "FakeHttp"
    assert opened == ["http", "http closed"]


async def test_auto_falls_back_to_the_browser_when_refused() -> None:
    FakeHttp.status = 403

    assert await use("auto") == "FakeBrowser"
    assert opened == ["http", "http closed", "browser", "http closed"]


async def test_forced_http_does_not_fall_back() -> None:
    FakeHttp.status = 403

    with pytest.raises(BlockedError):
        await use("http")


@pytest.mark.parametrize(
    ("status", "error"), [(429, BlockedError), (0, ScrapeError), (503, ScrapeError)]
)
async def test_auto_stops_on_a_rate_limit_or_an_error(status: int, error: type[Exception]) -> None:
    """Only a 403 on the start page switches clients; a 429 asks for less traffic."""
    FakeHttp.status = status

    with pytest.raises(error):
        await use("auto")

    assert "browser" not in opened


async def test_the_start_page_is_opened_once() -> None:
    async with transports.open_adapter(
        "prm", transport="auto", headless=False, profile_dir=UNUSED_PROFILE
    ) as adapter:
        await adapter.warm_up()  # the runner warms up again

    assert FakeHttp.opens == 1


async def test_browser_mode_never_tries_http() -> None:
    assert await use("browser") == "FakeBrowser"
    assert opened[0] == "browser"
