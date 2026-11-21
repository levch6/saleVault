"""Browserless transport: curl_cffi with its built-in Chrome profile.

See docs/decisions/0002-fetching-through-the-shop-api.md. Same rules as the browser: same pace,
same stop on repeated 403/429, no proxies, no CAPTCHA solving. If the site does not accept it,
`auto` mode uses the real browser instead.
"""

import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Self

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from salevault.scraper.base import HttpResponse

log = logging.getLogger(__name__)


class HttpSession:
    def __init__(
        self, origin: str, *, impersonate: str = "chrome", timeout_s: float = 30.0
    ) -> None:
        self._origin = origin.rstrip("/")
        self._impersonate = impersonate
        self._timeout_s = timeout_s
        self._session: requests.AsyncSession | None = None
        self._referer = self._origin + "/"

    async def __aenter__(self) -> Self:
        self._session = requests.AsyncSession(impersonate=self._impersonate)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()

    async def open(self, url: str) -> int:
        try:
            response = await self._require().get(url, timeout=self._timeout_s)
        except RequestException as exc:
            log.warning("GET %s failed: %s", url, exc)
            return 0
        self._referer = url
        return int(response.status_code)

    async def post_json(
        self, path: str, body: Mapping[str, object], headers: Mapping[str, str]
    ) -> HttpResponse:
        request_headers = {"origin": self._origin, "referer": self._referer, **headers}
        try:
            response = await self._require().post(
                self._origin + path,
                json=dict(body),
                headers=request_headers,
                timeout=self._timeout_s,
            )
        except RequestException as exc:
            return HttpResponse(status=0, text=str(exc))
        return HttpResponse(status=int(response.status_code), text=response.text)

    def _require(self) -> requests.AsyncSession:
        if self._session is None:
            raise RuntimeError("HttpSession is not started; use `async with`")
        return self._session
