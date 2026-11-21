"""Site-agnostic scraper building blocks: segments, page results, adapter and transport."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from salevault.domain.models import CategoryNode, Gender, ProductRecord

TransportMode = Literal["auto", "browser", "http"]
"""`auto`: curl_cffi first, the browser if the start page refuses it (see transports.py)."""


@dataclass(frozen=True, slots=True)
class SiteInfo:
    """What the storage layer needs to know about a shop."""

    code: str
    name: str
    origin: str
    currency: str


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    """HTTP status; 0 means the request did not complete (network error or timeout)."""
    text: str


class Transport(Protocol):
    """How an adapter talks to a site. Implemented by `HttpSession` and `BrowserSession`; faked
    in tests."""

    async def open(self, url: str) -> int:
        """Navigate like a regular visitor; returns the HTTP status of the page."""
        ...

    async def get(self, url: str) -> HttpResponse:
        """Load a page like a visitor and return its HTML as served (status 0 on network errors)."""
        ...

    async def post_json(
        self, path: str, body: Mapping[str, object], headers: Mapping[str, str]
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class Segment:
    """A slice of the catalog small enough for the API's per-query item cap."""

    sex: str | None = None
    price: tuple[int, int] | None = None
    """Inclusive price bounds in whole currency units."""

    def with_price(self, low: int, high: int) -> Segment:
        return replace(self, price=(low, high))

    @property
    def key(self) -> str:
        parts = []
        if self.sex is not None:
            parts.append(f"sex={self.sex}")
        if self.price is not None:
            parts.append(f"price={self.price[0]}-{self.price[1]}")
        return ";".join(parts) or "all"


@dataclass(frozen=True, slots=True)
class FacetValue:
    code: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class Facets:
    sex: tuple[FacetValue, ...] = ()
    price_range: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class PageResult:
    count: int
    """Total number of items matching the segment (not just this page)."""
    items: tuple[ProductRecord, ...]
    facets: Facets
    raw: str
    """Raw response body, kept for archiving and fixtures."""
    invalid_items: int = 0
    """Items skipped because they failed validation."""
    category_tree: tuple[CategoryNode, ...] | None = None
    """The shop's category tree, when the request asked for it (root page only)."""


class SiteConfig(Protocol):
    """Static facts about a supported shop, shared by the CLI, the API and the adapter."""

    @property
    def code(self) -> str: ...
    @property
    def display_name(self) -> str: ...
    @property
    def origin(self) -> str: ...
    @property
    def concurrency(self) -> int: ...
    @property
    def headless(self) -> bool: ...
    @property
    def transport(self) -> TransportMode: ...
    @property
    def image_host(self) -> str:
        """Origin of the product pictures (allowed by the UI's Content-Security-Policy)."""
        ...

    @property
    def site_info(self) -> SiteInfo: ...

    def image_urls(self, name: str, version: str) -> tuple[str, str]:
        """(grid thumbnail, full size) URLs of a stored image reference."""
        ...


class SiteAdapter(Protocol):
    code: str
    page_size: int
    """Items per API page."""
    max_pages: int
    """Deepest page the API serves for one query."""

    async def warm_up(self) -> None: ...

    async def fetch_page(self, segment: Segment, page: int) -> PageResult: ...

    def root_segments(self, root: PageResult) -> list[Segment]:
        """Top-level split (by gender section) derived from the unfiltered first page."""
        ...

    def gender_of(self, segment: Segment) -> Gender: ...
