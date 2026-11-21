"""Hits prm.com for real (one page). Run manually: `uv run pytest -m live`."""

from pathlib import Path

import pytest

from salevault.scraper.base import Segment
from salevault.scraper.browser import BrowserSession
from salevault.scraper.sites.registry import PRM, create_adapter

pytestmark = pytest.mark.live


async def test_prm_first_page_matches_the_schema(tmp_path: Path) -> None:
    async with BrowserSession(tmp_path / "profile", headless=PRM.headless) as browser:
        adapter = create_adapter(PRM.code, browser)
        await adapter.warm_up()
        page = await adapter.fetch_page(Segment(), 1)

    assert page.count > 1000
    assert len(page.items) == adapter.page_size
    assert page.invalid_items == 0
    assert {f.code for f in page.facets.sex} >= {"M", "D"}
    assert page.facets.price_range is not None
    assert all(item.price_minor < item.price_regular_minor for item in page.items)
