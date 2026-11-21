"""Hits modivo.ua for real (two pages per test). Run manually: `uv run pytest -m live`."""

from pathlib import Path

import pytest

from salevault.scraper.base import Segment, Transport
from salevault.scraper.browser import BrowserSession
from salevault.scraper.http_transport import HttpSession
from salevault.scraper.sites.registry import MODIVO_UA, create_adapter

pytestmark = pytest.mark.live


async def check_two_pages(transport: Transport) -> None:
    adapter = create_adapter(MODIVO_UA.code, transport)
    await adapter.warm_up()
    root = await adapter.fetch_page(Segment(), 1)  # the start page, not loaded again
    second = await adapter.fetch_page(Segment(sex="kids"), 2)

    assert root.count > 10_000
    assert len(root.items) == adapter.page_size
    assert root.invalid_items == 0
    assert all(item.price_minor < item.price_regular_minor for item in root.items)
    assert all(item.sizes and item.image for item in root.items)
    assert len(second.items) == adapter.page_size
    assert second.invalid_items == 0


async def test_modivo_over_http_transport() -> None:
    async with HttpSession(MODIVO_UA.origin) as http:
        await check_two_pages(http)


async def test_modivo_in_the_browser(tmp_path: Path) -> None:
    async with BrowserSession(tmp_path / "profile", headless=MODIVO_UA.headless) as browser:
        await check_two_pages(browser)
