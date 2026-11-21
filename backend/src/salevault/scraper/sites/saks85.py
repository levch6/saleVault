"""Adapter for Saks85 (saks85.com): reads the product cards of the sale catalog pages.

The shop runs OpenCart with the ocFilter module. Its catalog pages are rendered on the server
and embed no product data for scripts, so the adapter reads the product cards of each page
(12 per page) and archives what it parsed as JSON.

robots.txt disallows `/*?page=` for every user agent, the spelling the shop's own pagination
links use, as well as page size, sort and filter parameters. Page 1 of every section is loaded
by the path the shop's menus link to; later pages are loaded as OpenCart's own non-SEO URL of the
same listing (`index.php?route=product/category&path=...&filter_ocfilter=...&page=N`, the form
the shop's page-size links use), which no rule matches. That is the owner's decision; see
docs/decisions/0008-reading-saks85.md.
"""

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from salevault.domain.discounts import to_minor
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
    HttpResponse,
    PageResult,
    Segment,
    SiteInfo,
    Transport,
    TransportMode,
)
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError
from salevault.scraper.sites.common import (
    ItemNormalizer,
    check_start_status,
    raise_for_status,
    short,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Saks85Category:
    """A top-level category of the catalog."""

    slug: str
    """Its path keyword, e.g. "odyag"."""
    path_id: str
    """OpenCart's category id, `path=` in the non-SEO URL."""


@dataclass(frozen=True, slots=True)
class Saks85Gender:
    """A value of the shop's gender filter."""

    path: str
    """Its ocFilter path, e.g. "stat/choloviche"."""
    selection: str
    """Its ocFilter value in the non-SEO URL, e.g. "10024:4252492559"."""
    gender: Gender


@dataclass(frozen=True, slots=True)
class Saks85Config:
    code: str
    display_name: str
    origin: str
    sale_path: str
    """The ocFilter path of the sale, e.g. "special/rasprodazha"."""
    sale_selection: str
    """Its ocFilter value in the non-SEO URL."""
    catalog: Saks85Category
    """The whole catalog (OpenCart's path 0): the sale page and its expected item count."""
    categories: Mapping[str, Saks85Category]
    """Top-level categories; together they hold the whole sale."""
    genders: Mapping[str, Saks85Gender]
    currency: str = "UAH"
    concurrency: int = 1
    headless: bool = False
    transport: TransportMode = "auto"
    image_host: str = "https://saks85.com"
    thumb_size: str = "352x530"
    """Sizes of OpenCart's image cache: 352x530 in listings, 1200x1800 on product pages."""
    full_size: str = "1200x1800"

    def image_urls(self, name: str, version: str) -> tuple[str, str]:
        """`name` is the image path under the cache without its size, e.g. "a/b.webp"."""
        stem, dot, ext = name.rpartition(".")
        base = f"{self.image_host}/image/cache/{stem}"
        return f"{base}-{self.thumb_size}{dot}{ext}", f"{base}-{self.full_size}{dot}{ext}"

    @property
    def sections(self) -> dict[str, tuple[Saks85Gender, Saks85Category]]:
        """Segments of a run: every gender in every category, e.g. "men-clothing"."""
        return {
            f"{g}-{c}": (gender, category)
            for g, gender in self.genders.items()
            for c, category in self.categories.items()
        }

    @property
    def site_info(self) -> SiteInfo:
        return SiteInfo(
            code=self.code, name=self.display_name, origin=self.origin, currency=self.currency
        )


# --- What a catalog page holds ---------------------------------------------------------------


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class RawSize(_Raw):
    label: str = Field(min_length=1)
    available: bool


class RawCard(_Raw):
    url: str
    brand: str = Field(min_length=1)
    title: str = Field(min_length=1)
    price: str
    """As shown, e.g. "6 952" and the currency word."""
    price_regular: str | None = None
    images: list[str] = Field(default_factory=list)
    sizes: list[RawSize] = Field(default_factory=list)


class RawSummary(_Raw):
    """The numbers of the page's "items 13 to 24 of 2873 (240 pages)" line."""

    first: int
    last: int
    total: int
    pages: int


class RawListing(_Raw):
    heading: str | None = None
    currency: str | None = None
    summary: RawSummary | None = None
    cards: list[dict[str, Any]] = Field(default_factory=list)


_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_CHALLENGE_MARKERS = ("cf-chl", "cf_chl_opt", "Just a moment...", "challenge-platform")
"""Signs of a bot check page. Normal pages carry a Cloudflare script too, so these are only
checked on a page without a listing."""


@dataclass
class _Card:
    url: str | None = None
    brand: list[str] = field(default_factory=list)
    title: list[str] = field(default_factory=list)
    price: list[str] = field(default_factory=list)
    price_regular: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    sizes: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "brand": _text(self.brand),
            "title": _text(self.title),
            "price": _text(self.price),
            "price_regular": _text(self.price_regular) or None,
            "images": self.images,
            "sizes": self.sizes,
        }


_CARD_FIELDS = {
    "catalog-card__brand": "brand",
    "catalog-card__title": "title",
    "catalog-card__price-prev": "price_regular",
    "catalog-card__price": "price",
}


class _ListingParser(HTMLParser):
    """Collects the heading, the currency, the item count line and the product cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading: list[str] | None = None
        self.currency: str | None = None
        self.summary: list[str] | None = None
        self.cards: list[_Card] = []
        self._stack: list[tuple[str, frozenset[str]]] = []
        self._card: _Card | None = None
        self._card_level = 0
        self._size: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = frozenset(attr.get("class", "").split())
        if tag == "input" and "currency_ecommerce_code" in classes:
            self.currency = attr.get("value", "").strip()
        if tag == "div" and "catalog-card" in classes:
            self._card = _Card()
            self.cards.append(self._card)
            self._card_level = len(self._stack) + 1
        elif self._card is not None:
            self._card_tag(self._card, tag, attr, classes)
        if tag == "h1" and "catalog__title" in classes and self.heading is None:
            self.heading = []
        if "text-right" in classes and self._inside("toolbar4") and self.summary is None:
            self.summary = []
        if tag not in _VOID:
            self._stack.append((tag, classes))

    def _card_tag(
        self, card: _Card, tag: str, attr: dict[str, str], classes: frozenset[str]
    ) -> None:
        if tag == "a" and card.url is None and self._inside("catalog-card__photo"):
            card.url = attr.get("href", "").strip()
        elif tag == "img" and classes & {"catalog-card__main", "catalog-card__secondary"}:
            src = attr.get("data-src") or attr.get("src") or ""
            if src and src not in card.images:
                card.images.append(src.strip())
        elif "catalog-card__size" in classes:
            available = "catalog-card__size--disabled" not in classes
            self._size = {"label": [], "available": available}
            card.sizes.append(self._size)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:  # a self-closed element has no content
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, _ in self._stack):
            return  # a stray end tag
        while self._stack:
            open_tag, classes = self._stack.pop()
            self._closed(classes)
            if open_tag == tag:
                break
        if self._card is not None and len(self._stack) < self._card_level:
            self._card = None

    def _closed(self, classes: frozenset[str]) -> None:
        if "catalog-card__size" in classes and self._size is not None:
            self._size["label"] = _text(self._size["label"])
            self._size = None

    def handle_data(self, data: str) -> None:
        if self.heading is not None and self._inside("catalog__title", tag="h1"):
            self.heading.append(data)
        if self.summary is not None and self._inside("text-right") and self._inside("toolbar4"):
            self.summary.append(data)
        if self._card is None:
            return
        if self._size is not None:
            self._size["label"].append(data)
            return
        for _, classes in reversed(self._stack):
            for css, name in _CARD_FIELDS.items():
                if css in classes:
                    getattr(self._card, name).append(data)
                    return

    def _inside(self, css: str, *, tag: str | None = None) -> bool:
        return any(css in classes and tag in (None, open_tag) for open_tag, classes in self._stack)


def extract_listing(html: str) -> dict[str, Any] | None:
    """What a catalog page shows, as JSON-ready data, or None if it is not a catalog page."""
    parser = _ListingParser()
    parser.feed(html)
    parser.close()
    if parser.heading is None and not parser.cards:
        return None
    numbers = [int(n) for n in re.findall(r"\d+", _text(parser.summary or []))]
    summary = (
        dict(zip(("first", "last", "total", "pages"), numbers, strict=True))
        if len(numbers) == 4
        else None
    )
    return {
        "heading": _text(parser.heading) if parser.heading is not None else None,
        "currency": parser.currency,
        "summary": summary,
        "cards": [card.to_json() for card in parser.cards],
    }


# --- Adapter ---------------------------------------------------------------------------------


class Saks85Adapter:
    page_size = 12
    max_pages = 1000
    """No depth cap is known; this limit only guards against a runaway plan."""

    def __init__(self, config: Saks85Config, transport: Transport) -> None:
        self.config = config
        self.code = config.code
        self._transport = transport
        self._sections = config.sections
        self._normalize_items = ItemNormalizer()
        self._start_page: HttpResponse | None = None
        self._warmed_up = False

    async def warm_up(self) -> None:
        """Open the sale like a visitor; that page is also page 1 of the root request."""
        if self._warmed_up:
            return
        url = self.page_url(Segment(), 1)
        try:
            response = await self._transport.get(url)
        except Exception as exc:  # navigation timeouts, DNS, browser errors
            raise ScrapeError(f"Could not open {url}: {exc}") from exc
        check_start_status(response.status, url)
        self._start_page = response
        self._warmed_up = True

    def page_url(self, segment: Segment, page: int) -> str:
        """Page 1 by its path, as the menus link to it; later pages as OpenCart's non-SEO URL
        with `&page=N` (robots.txt disallows `?page=`, see the module docstring)."""
        if segment.price is not None:
            raise ValueError("Saks85 segments cannot be filtered by price")
        config = self.config
        if segment.sex is None:
            category, gender = config.catalog, None
        else:
            gender, category = self._sections[segment.sex]
        if page == 1:
            path = f"/{category.slug}/{config.sale_path}/"
            if gender is not None:
                path += f"{gender.path}/"
            return config.origin + path
        selection = config.sale_selection
        if gender is not None:
            selection += f";{gender.selection}"
        return (
            f"{config.origin}/index.php?route=product/category"
            f"&path={category.path_id}&filter_ocfilter={selection}&page={page}"
        )

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        if segment == Segment() and page == 1 and self._start_page is not None:
            response, self._start_page = self._start_page, None
        else:
            response = await self._transport.get(self.page_url(segment, page))
        return self.parse_page(response, segment, page)

    def parse_page(
        self, response: HttpResponse, segment: Segment | None = None, page: int = 1
    ) -> PageResult:
        raise_for_status(response)
        data = extract_listing(response.text)
        if data is None:
            if any(marker in response.text for marker in _CHALLENGE_MARKERS):
                raise BlockedError("Got a bot check instead of the catalog", raw=response.text)
            raise ContractError("The page has no product listing", raw=response.text)
        return self.parse_listing(data, segment, page)

    def parse_listing(
        self, data: Mapping[str, Any], segment: Segment | None = None, page: int = 1
    ) -> PageResult:
        """A page from what `extract_listing` took from it (also the archived format)."""
        text = json.dumps(data, ensure_ascii=False)
        try:
            listing = RawListing.model_validate(data)
        except ValidationError as exc:
            raise ContractError(f"Unexpected product listing: {short(str(exc))}", raw=text) from exc
        if listing.currency != self.config.currency:
            raise ContractError(f"Unexpected currency {listing.currency!r}", raw=text)
        summary = listing.summary
        if summary is None:
            if listing.cards:
                raise ContractError("The page has products but no item count", raw=text)
            # No products: an empty section, or a page past the end (the catalog can shrink
            # during a run).
            return PageResult(count=0, items=(), facets=Facets(), raw=text)
        if summary.first != (page - 1) * self.page_size + 1:
            log.debug("Page %d is not what the shop served (%d pages)", page, summary.pages)
            return PageResult(count=summary.total, items=(), facets=Facets(), raw=text)
        category = self._category(segment or Segment(), listing.heading)
        items, invalid = self._normalize_items(
            listing.cards,
            lambda card: self.normalize(RawCard.model_validate(card), category),
            raw=text,
        )
        return PageResult(
            count=summary.total, items=items, facets=Facets(), raw=text, invalid_items=invalid
        )

    def _category(self, segment: Segment, heading: str | None) -> CategoryRef | None:
        """The segment's category, named by the page's heading."""
        if segment.sex is None or not heading:
            return None
        _, category = self._sections[segment.sex]
        return CategoryRef(external_id=category.path_id, name=heading)

    def root_segments(self, root: PageResult) -> list[Segment]:
        return [Segment(sex=key) for key in self._sections]

    def gender_of(self, segment: Segment) -> Gender:
        if segment.sex is None:
            return Gender(0)
        gender, _ = self._sections[segment.sex]
        return gender.gender

    def normalize(self, raw: RawCard, category: CategoryRef | None = None) -> ProductRecord:
        origin = self.config.origin
        if not raw.url.startswith(origin + "/"):
            raise ValueError(f"Unexpected product URL {raw.url!r}")
        price = to_minor(money(raw.price))
        regular = to_minor(money(raw.price_regular)) if raw.price_regular else price
        sizes = _sizes(raw.sizes)
        available = any(s.in_stock for s in sizes) if sizes else True
        images = _images(raw.images, self.config.image_host)
        return ProductRecord.create(
            site=self.code,
            external_id=product_id(raw.url[len(origin) + 1 :]),
            url=raw.url,
            name=raw.title,
            subtitle=None,
            brand=BrandRef(external_id=raw.brand, name=raw.brand),
            color=None,
            image=images[0] if images else None,
            gallery=images,
            categories=(category,) if category is not None else (),
            price_minor=price,
            price_regular_minor=regular,
            price_min30_minor=None,
            available_for_buy=available,
            sizes=sizes,
        )


_ID_LIMIT = 64


def product_id(path: str) -> str:
    """A stable id from the product's path, which is unique (the cards carry no product id).

    The path is percent-decoded (listings encode "+" as "%2B", the sitemap does not). A path
    longer than the database's 64 characters keeps its start and gets a hash of the whole."""
    path = unquote(path.split("?", 1)[0].split("#", 1)[0]).strip("/")
    if len(path) <= _ID_LIMIT:
        return path
    digest = hashlib.blake2b(path.encode(), digest_size=8).hexdigest()
    return f"{path[: _ID_LIMIT - len(digest) - 1]}~{digest}"


_MONEY = re.compile(r"(\d[\d\s]*)(?:[.,](\d{1,2}))?")


def money(text: str) -> Decimal:
    """A price as shown: digits grouped by spaces, an optional decimal part, the currency."""
    match = _MONEY.search(text)
    if match is None:
        raise ValueError(f"No price in {text!r}")
    whole = re.sub(r"\s", "", match.group(1))
    return Decimal(f"{whole}.{match.group(2)}" if match.group(2) else whole)


def _sizes(raw: list[RawSize]) -> tuple[SizeRecord, ...]:
    sizes: dict[str, SizeRecord] = {}
    for size in raw:
        label = size.label.strip()
        if label in sizes:
            continue  # the size id is its label, so a label shown twice is one size
        sizes[label] = SizeRecord(
            external_id=label,
            label=label,
            variation_id=label,
            ean=None,
            availability="IN_STOCK" if size.available else "OUT_OF_STOCK",
            in_stock=size.available,
        )
    return tuple(sizes.values())


_IMAGE = re.compile(r"/image/cache/(catalog/.+)-\d+x\d+\.([A-Za-z0-9]+)$")


def _images(urls: list[str], host: str) -> tuple[ImageRef, ...]:
    refs: list[ImageRef] = []
    for url in urls:
        match = _IMAGE.search(url) if url.startswith(host + "/") else None
        if match is None:  # a placeholder or another host
            log.debug("Ignoring an image URL of an unknown shape: %s", url)
            continue
        ref = ImageRef(name=f"{match.group(1)}.{match.group(2)}", version="")
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())
