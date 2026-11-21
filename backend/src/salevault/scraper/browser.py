"""Real-browser transport: Chromium via Playwright, API calls via `fetch` from the page.

See docs/decisions/0002-fetching-through-the-shop-api.md: a stock Chromium without stealth
plugins that calls the API from the shop's page, like the shop's own frontend.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Self

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from salevault.scraper.base import HttpResponse

log = logging.getLogger(__name__)

_FETCH_JS = """
async ({ path, body, headers, timeoutMs }) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(path, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      credentials: 'same-origin',
      signal: ctrl.signal,
    });
    return { status: r.status, text: await r.text() };
  } catch (e) {
    return { status: 0, text: String(e) };
  } finally {
    clearTimeout(timer);
  }
}
"""


class BrowserSession:
    """A persistent Chromium profile with one page; usable as an async context manager."""

    def __init__(
        self,
        profile_dir: Path,
        *,
        headless: bool = True,
        locale: str = "uk-UA",
        request_timeout_s: float = 30.0,
        navigation_timeout_s: float = 60.0,
    ) -> None:
        self._profile_dir = profile_dir
        self._headless = headless
        self._locale = locale
        self._request_timeout_ms = int(request_timeout_s * 1000)
        self._navigation_timeout_ms = int(navigation_timeout_s * 1000)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_url: str | None = None

    async def __aenter__(self) -> Self:
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=self._headless,
            locale=self._locale,
            viewport={"width": 1440, "height": 900},
        )
        self._page = await self._new_page()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def open(self, url: str) -> int:
        page = self._require_page()
        response = await page.goto(url, wait_until="load", timeout=self._navigation_timeout_ms)
        self._last_url = url
        return response.status if response is not None else 0

    async def post_json(
        self, path: str, body: Mapping[str, object], headers: Mapping[str, str]
    ) -> HttpResponse:
        page = self._require_page()
        args = {
            "path": path,
            "body": dict(body),
            "headers": dict(headers),
            "timeoutMs": self._request_timeout_ms,
        }
        try:
            result = await page.evaluate(_FETCH_JS, args)
        except PlaywrightError as exc:
            # Page crashed or navigated away; recover and let the caller retry.
            log.warning("Browser page failed (%s); reopening", exc)
            await self._recover()
            return HttpResponse(status=0, text=str(exc))
        return HttpResponse(status=int(result["status"]), text=str(result["text"]))

    async def _new_page(self) -> Page:
        assert self._context is not None
        pages = self._context.pages
        page = pages[0] if pages else await self._context.new_page()
        page.set_default_timeout(self._navigation_timeout_ms)
        return page

    async def _recover(self) -> None:
        assert self._context is not None
        if self._page is not None and not self._page.is_closed():
            await self._page.close()
        self._page = await self._context.new_page()
        if self._last_url is not None:
            await self.open(self._last_url)

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession is not started; use `async with`")
        return self._page
