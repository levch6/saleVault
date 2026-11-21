"""Test doubles: a synthetic catalog adapter and a scripted transport."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field

from salevault.domain.models import (
    BrandRef,
    CategoryRef,
    Gender,
    ImageRef,
    ProductRecord,
    SizeRecord,
)
from salevault.scraper.base import (
    Facets,
    FacetValue,
    HttpResponse,
    PageResult,
    Segment,
    SiteInfo,
)
from salevault.scraper.errors import ContractError

GENDERS = {"M": Gender.MEN, "D": Gender.WOMEN, "H": Gender.HOME}
FAKE_SITE = SiteInfo(code="fake", name="Fake shop", origin="https://shop.test", currency="UAH")


@dataclass(frozen=True)
class FakeItem:
    id: str
    sex: frozenset[str]
    price: int
    """Whole currency units."""


def make_record(
    item: FakeItem,
    *,
    site: str = "fake",
    regular: int | None = None,
    min30: int | None = None,
    brand: str = "1",
) -> ProductRecord:
    """A realistic record: brand, a two-level category path, one size in stock and one not."""
    return ProductRecord.create(
        site=site,
        external_id=item.id,
        url=f"https://shop.test/p/{item.id}",
        name=f"Product {item.id}",
        subtitle=None,
        brand=BrandRef(external_id=brand, name=f"Brand {brand}"),
        color="black",
        image=ImageRef(name=f"{item.id}_F1.jpg", version="1"),
        gallery=(ImageRef(name=f"{item.id}_F2.jpg", version="1"),),
        categories=(
            CategoryRef(external_id="100", name="Root"),
            CategoryRef(external_id="101", name="Leaf"),
        ),
        price_minor=item.price * 100,
        price_regular_minor=(regular if regular is not None else item.price * 2) * 100,
        price_min30_minor=min30 * 100 if min30 is not None else None,
        available_for_buy=True,
        sizes=(
            SizeRecord(
                external_id="1",
                label="S",
                variation_id=f"{item.id}-S",
                ean=None,
                availability="IN_STOCK",
                in_stock=True,
            ),
            SizeRecord(
                external_id="2",
                label="M",
                variation_id=f"{item.id}-M",
                ean=None,
                availability="OUT_OF_STOCK",
                in_stock=False,
            ),
        ),
    )


def make_catalog(
    per_sex: Mapping[str, int], *, unisex: int = 0, start_price: int = 100
) -> list[FakeItem]:
    """Items with distinct prices; `unisex` extra items belong to both M and D."""
    items: list[FakeItem] = []
    price = start_price
    for sex, n in per_sex.items():
        for _ in range(n):
            items.append(FakeItem(f"{sex}{len(items)}", frozenset({sex}), price))
            price += 7
    for _ in range(unisex):
        items.append(FakeItem(f"U{len(items)}", frozenset({"M", "D"}), price))
        price += 7
    return items


@dataclass
class FakeAdapter:
    """Serves a synthetic catalog with the real API's constraints (page size, page cap)."""

    items: list[FakeItem]
    page_size: int = 10
    max_pages: int = 5
    code: str = "fake"
    failures: dict[tuple[str, int], list[BaseException]] = field(
        default_factory=lambda: defaultdict(list)
    )
    blank_pages: set[tuple[str, int]] = field(default_factory=set)
    """Pages that come back empty, simulating items lost to catalog drift."""
    calls: list[tuple[str, int]] = field(default_factory=list)
    warmed: bool = False
    hang_on: tuple[str, int] | None = None
    """A page that never answers, to test cancellation from outside."""
    hung: asyncio.Event = field(default_factory=asyncio.Event)

    async def warm_up(self) -> None:
        self.warmed = True

    def fail(self, segment: Segment, page: int, *errors: BaseException) -> None:
        self.failures[(segment.key, page)].extend(errors)

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        self.calls.append((segment.key, page))
        if (segment.key, page) == self.hang_on:
            self.hung.set()
            await asyncio.Event().wait()
        pending = self.failures.get((segment.key, page))
        if pending:
            raise pending.pop(0)
        if page > self.max_pages:
            raise ContractError(f"page {page} is beyond the cap")

        by_sex = [i for i in self.items if segment.sex is None or segment.sex in i.sex]
        matched = sorted(
            (
                i
                for i in by_sex
                if segment.price is None or segment.price[0] <= i.price <= segment.price[1]
            ),
            key=lambda i: (i.price, i.id),
        )
        chunk = matched[(page - 1) * self.page_size : page * self.page_size]
        if (segment.key, page) in self.blank_pages:
            chunk = []
        sex_counts = Counter(s for i in self.items for s in i.sex)
        prices = [i.price for i in by_sex]
        facets = Facets(
            sex=tuple(FacetValue(code, code, n) for code, n in sorted(sex_counts.items())),
            price_range=(min(prices), max(prices)) if prices else None,
        )
        return PageResult(
            count=len(matched),
            items=tuple(make_record(i) for i in chunk),
            facets=facets,
            raw=f'{{"segment": "{segment.key}", "page": {page}}}',
        )

    def root_segments(self, root: PageResult) -> list[Segment]:
        return [Segment(sex=f.code) for f in root.facets.sex if f.count > 0]

    def gender_of(self, segment: Segment) -> Gender:
        return GENDERS.get(segment.sex or "", Gender(0))


@dataclass
class FakeTransport:
    """Returns scripted responses in order and records what was sent."""

    responses: list[HttpResponse] = field(default_factory=list)
    open_status: int = 200
    opened: list[str] = field(default_factory=list)
    posts: list[tuple[str, dict[str, object], dict[str, str]]] = field(default_factory=list)

    async def open(self, url: str) -> int:
        self.opened.append(url)
        return self.open_status

    async def post_json(
        self, path: str, body: Mapping[str, object], headers: Mapping[str, str]
    ) -> HttpResponse:
        self.posts.append((path, dict(body), dict(headers)))
        return self.responses.pop(0)


def opener(adapter: FakeAdapter) -> Callable[[], AbstractAsyncContextManager[FakeAdapter]]:
    """`open_adapter` for `execute_run` that hands out an already built fake."""

    @asynccontextmanager
    async def _open() -> AsyncIterator[FakeAdapter]:
        yield adapter

    return _open
