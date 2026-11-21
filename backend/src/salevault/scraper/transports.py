"""Pick how to talk to a shop: lightweight HTTP (curl_cffi) or a real browser (Playwright)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from salevault.scraper.base import SiteAdapter, TransportMode
from salevault.scraper.browser import BrowserSession
from salevault.scraper.errors import BlockedError
from salevault.scraper.http_transport import HttpSession
from salevault.scraper.sites.registry import create_adapter, get_config

log = logging.getLogger(__name__)


@asynccontextmanager
async def open_adapter(
    code: str, *, transport: TransportMode, headless: bool, profile_dir: Path
) -> AsyncIterator[SiteAdapter]:
    """`auto` tries HTTP first and uses the browser if the shop does not serve the HTTP client.

    That is the only case that switches clients: a 403 on the start page, before any catalog
    request. A 429 asks for less traffic and network errors would hit the browser too, so both
    stop the run instead.
    """
    if transport in ("auto", "http"):
        async with HttpSession(get_config(code).origin) as http:
            adapter = create_adapter(code, http)
            try:
                await adapter.warm_up()
            except BlockedError as exc:
                if transport == "http" or exc.status != 403:
                    raise
                log.warning(
                    "%s: the start page refused the HTTP client (403); using the browser", code
                )
            else:
                log.info("%s: using the HTTP transport (no browser window)", code)
                yield adapter
                return
    async with BrowserSession(profile_dir, headless=headless) as browser:
        log.info("%s: using the browser transport (%s)", code, "headless" if headless else "window")
        yield create_adapter(code, browser)
