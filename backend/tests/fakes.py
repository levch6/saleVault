"""Test doubles: a synthetic catalog adapter and a scripted transport."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from salevault.domain.models import BrandRef, Gender, ProductRecord
from salevault.scraper.base import Facets, FacetValue, HttpResponse, PageResult, Segment
from salevault.scraper.errors import ContractError

GENDERS = {"M": Gender.MEN, "D": Gender.WOMEN, "H": Gender.HOME}


@dataclass(frozen=True)
class FakeItem:
    id: str
    sex: frozenset[str]
    price: int
    """Whole currency units."""


def make_record(item: FakeItem, *, site: str = "fake") -> ProductRecord:
    return ProductRecord.create(
        site=site,
        external_id=item.id,
        url=f"https://shop.test/p/{item.id}",
        name=f"Product {item.id}",
        subtitle=None,
        brand=BrandRef(external_id="1", name="Brand"),
        color=None,
        image=None,
        gallery=(),
        categories=(),
        price_minor=item.price * 100,
        price_regular_minor=item.price * 200,
        price_min30_minor=None,
        available_for_buy=True,
        sizes=(),
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
    failures: dict[tuple[str, int], list[Exception]] = field(
        default_factory=lambda: defaultdict(list)
    )
    blank_pages: set[tuple[str, int]] = field(default_factory=set)
    """Pages that come back empty, simulating items lost to catalog drift."""
    calls: list[tuple[str, int]] = field(default_factory=list)
    warmed: bool = False

    async def warm_up(self) -> None:
        self.warmed = True

    def fail(self, segment: Segment, page: int, *errors: Exception) -> None:
        self.failures[(segment.key, page)].extend(errors)

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        self.calls.append((segment.key, page))
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
