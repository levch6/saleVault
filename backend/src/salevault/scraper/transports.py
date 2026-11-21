"""Pick how to talk to a shop: lightweight HTTP (curl_cffi) or a real browser (Playwright)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from salevault.scraper.browser import BrowserSession
from salevault.scraper.http_transport import HttpSession
from salevault.scraper.sites.answear_platform import AnswearPlatformAdapter, TransportMode
from salevault.scraper.sites.registry import create_adapter, get_config

log = logging.getLogger(__name__)


@asynccontextmanager
async def open_adapter(
    code: str, *, transport: TransportMode, headless: bool, profile_dir: Path
) -> AsyncIterator[AnswearPlatformAdapter]:
    """`auto` tries HTTP first and falls back to the browser if the warm-up page is refused."""
    config = get_config(code)
    if transport in ("auto", "http"):
        async with HttpSession(config.origin) as http:
            status = await http.open(config.origin + config.warmup_path)
            if status == 200 or transport == "http":
                log.info("%s: using the HTTP transport (no browser window)", code)
                yield create_adapter(code, http)
                return
        log.warning("%s: HTTP transport got HTTP %s at warm-up; using the browser", code, status)
    async with BrowserSession(profile_dir, headless=headless) as browser:
        log.info("%s: using the browser transport (%s)", code, "headless" if headless else "window")
        yield create_adapter(code, browser)
