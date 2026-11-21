"""Site-agnostic scraper building blocks: segments, page results, adapter and transport."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from salevault.domain.models import Gender, ProductRecord


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
    """How an adapter talks to a site. Implemented by `BrowserSession`; faked in tests."""

    async def open(self, url: str) -> int:
        """Navigate like a regular visitor; returns the HTTP status of the page."""
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
