"""Adapter for Modivo (modivo.ua): reads the sale catalog pages and the state they embed.

The shop's robots.txt disallows its APIs (`/m-api/`, `/t-api/`, `/n-api/`) for every user agent,
as well as most filter combinations of the catalog pages, but allows the discount filter
`discount:~r-5-99` (its `Allow` rule is longer than the `Disallow` rules the URL also matches).
The catalog pages are rendered on the server (Nuxt 2) and embed the page's state for their
scripts: 72 items per page with prices, sizes and pictures, plus the item count and the number
of pages. The state is read as data by `nuxt_state`, never run. See
docs/decisions/0007-reading-modivo.md.
"""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from salevault.domain.discounts import to_minor
from salevault.domain.models import BrandRef, Gender, ImageRef, ProductRecord, SizeRecord
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
    clean,
    raise_for_status,
    short,
)
from salevault.scraper.sites.nuxt_state import NuxtStateError, read_nuxt_state

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModivoSection:
    """A gender section of the catalog, e.g. "/c/zhinky"."""

    path: str
    gender: Gender


@dataclass(frozen=True, slots=True)
class ModivoConfig:
    code: str
    display_name: str
    origin: str
    root_path: str
    """The whole catalog, e.g. "/c/modivo": its sale is the start page and gives the count."""
    sale_filter: str
    """The discount filter of the sale, e.g. "discount:~r-5-99"; robots.txt allows only this
    spelling of it."""
    sections: Mapping[str, ModivoSection]
    """Gender sections; together they hold the whole sale."""
    currency: str = "UAH"
    concurrency: int = 1
    headless: bool = False
    transport: TransportMode = "auto"
    image_host: str = "https://img.modivo.cloud"
    thumb_size: str = "product"
    """Transformations of the image CDN: `product` is 560 x 746 px, `zoomapp` 1536 x 2048."""
    full_size: str = "zoomapp"

    def image_urls(self, name: str, version: str) -> tuple[str, str]:
        """`name` is the picture's path on the CDN, e.g. "6/2/5/4/<hash>_01_<code>.jpg"."""
        base = self.image_host
        return f"{base}/{self.thumb_size}({name},webp)", f"{base}/{self.full_size}({name},webp)"

    @property
    def site_info(self) -> SiteInfo:
        return SiteInfo(
            code=self.code, name=self.display_name, origin=self.origin, currency=self.currency
        )


# --- What a catalog page holds ---------------------------------------------------------------


class _Each:
    """In a `_LISTING_SHAPE`: every value of a mapping has this shape."""

    def __init__(self, shape: Any) -> None:
        self.shape = shape


_AMOUNT = {"amount": None}
_LISTING_SHAPE: dict[str, Any] = {
    "listingDetails": {
        "currentPage": None,
        "totalPages": None,
        "totalProducts": None,
        "productsPerPage": None,
    },
    "products": [
        {
            "sku": None,
            "currency": None,
            "mainProductImageSlug": None,
            "designSystem": {
                "id": None,
                "brand": None,
                "name": None,
                "url": None,
                "images": [{"src": None, "alt": None}],
            },
        }
    ],
    "productsAnalytics": [
        {
            "sku": None,
            "color": None,
            "price": {
                "regular": _AMOUNT,
                "promotional": _AMOUNT,
                "omnibus": _AMOUNT,
                "discount": None,
            },
            "variants": _Each(
                {
                    "id": None,
                    "size": None,
                    "sort_order": None,
                    "availability": None,
                    "values": _Each({"value": {"label": None}}),
                }
            ),
        }
    ],
}
"""The parts of a page's state the adapter reads (and archives). The models below validate it;
the adapter always parses this pruned form, so a field missing here fails the tests."""


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class RawAmount(_Raw):
    amount: Decimal | None = None


class RawPrice(_Raw):
    regular: RawAmount = Field(default_factory=RawAmount)
    promotional: RawAmount = Field(default_factory=RawAmount)
    """The current price."""
    omnibus: RawAmount = Field(default_factory=RawAmount)
    """The lowest price of the 30 days before the discount, where the shop shows it."""
    discount: str | None = None
    """The shop's own percent, e.g. "25%" (not used: the adapter computes it the same way)."""


class RawSizeValue(_Raw):
    label: str = Field(min_length=1)


class RawSizeAttribute(_Raw):
    value: RawSizeValue


class RawVariant(_Raw):
    id: str | None = None
    size: str | None = None
    sort_order: int | None = None
    availability: str
    values: dict[str, RawSizeAttribute] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def _empty_list_is_empty_object(cls, value: object) -> object:
        return {} if value == [] else value  # the backend may encode an empty map as []


class RawDetails(_Raw):
    """An item's entry in the page's product analytics: prices, color, sizes."""

    sku: str
    color: str | None = None
    price: RawPrice
    variants: dict[str, RawVariant] = Field(default_factory=dict)

    @field_validator("variants", mode="before")
    @classmethod
    def _empty_list_is_empty_object(cls, value: object) -> object:
        return {} if value == [] else value


class RawImage(_Raw):
    src: str
    alt: str | None = None


class RawDesign(_Raw):
    id: str
    brand: str = Field(min_length=1)
    name: str = Field(min_length=1)
    """The kind of item, its color and sometimes its fit, separated by `_PARTS`."""
    url: str
    images: list[RawImage] = Field(default_factory=list)


class RawCard(_Raw):
    """An item's product card: name, link and pictures."""

    sku: str = Field(min_length=1, max_length=64)
    currency: str
    design: RawDesign = Field(alias="designSystem")
    main_image: str | None = Field(default=None, alias="mainProductImageSlug")


class RawListingDetails(_Raw):
    current_page: int = Field(alias="currentPage")
    total_pages: int = Field(alias="totalPages")
    total_products: int = Field(alias="totalProducts")
    products_per_page: int = Field(alias="productsPerPage")


class RawListing(_Raw):
    listing_details: RawListingDetails = Field(alias="listingDetails")
    products: list[dict[str, Any]]
    products_analytics: list[dict[str, Any]] = Field(alias="productsAnalytics")


_PARTS = " \N{MIDDLE DOT} "
"""Separates the parts of a card's name, e.g. "Winter jacket . Black . Slim Fit"."""

_CHALLENGE_MARKERS = ("cf-chl", "cf_chl_opt", "Just a moment...", "challenge-platform")
"""Signs of a bot check page. Normal pages carry a Cloudflare script too, so these are only
checked on a page without a listing."""


def extract_listing(html: str) -> dict[str, Any] | None:
    """The listing of a catalog page, as `_LISTING_SHAPE` describes it (JSON-ready), or None if
    the page has no product listing. Raises `NuxtStateError` if the page's state is unreadable."""
    state = read_nuxt_state(html)
    if not isinstance(state, dict):
        return None
    data = state.get("data")
    page = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    pinia = state.get("pinia")
    search = pinia.get("searchCategory") if isinstance(pinia, dict) else None
    if "listingDetails" not in page or "products" not in page or not isinstance(search, dict):
        return None
    listing = {
        "listingDetails": page["listingDetails"],
        "products": page["products"],
        "productsAnalytics": search.get("productsAnalytics"),
    }
    pruned: dict[str, Any] = _prune(listing, _LISTING_SHAPE)
    return pruned


def _prune(value: Any, shape: Any) -> Any:
    """The parts of `value` that `shape` names: a dict names keys (each with its own shape), a
    one-element list the shape of every item, `_Each` that of every value of a mapping, None
    the whole value. A value of another form is kept, so that the models report it."""
    if isinstance(shape, dict) and isinstance(value, dict):
        return {key: _prune(value[key], inner) for key, inner in shape.items() if key in value}
    if isinstance(shape, list) and isinstance(value, list):
        return [_prune(item, shape[0]) for item in value]
    if isinstance(shape, _Each) and isinstance(value, dict):
        return {key: _prune(item, shape.shape) for key, item in value.items()}
    return value


# --- Adapter ---------------------------------------------------------------------------------


class ModivoAdapter:
    page_size = 72
    max_pages = 2000
    """No cap seen: the last page of the whole sale (page 886 of 886) is served. This limit only
    guards against a runaway plan."""

    def __init__(self, config: ModivoConfig, transport: Transport) -> None:
        self.config = config
        self.code = config.code
        self._transport = transport
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
        """The sale of a section, e.g. "/c/zhinky/discount:~r-5-99?p=2" (the shop's own
        pagination)."""
        if segment.price is not None:
            raise ValueError("Modivo segments cannot be filtered by price")
        config = self.config
        path = config.root_path if segment.sex is None else config.sections[segment.sex].path
        url = f"{config.origin}{path}/{config.sale_filter}"
        return f"{url}?p={page}" if page > 1 else url

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        if segment == Segment() and page == 1 and self._start_page is not None:
            response, self._start_page = self._start_page, None
        else:
            response = await self._transport.get(self.page_url(segment, page))
        return self.parse_page(response, page)

    def parse_page(self, response: HttpResponse, page: int = 1) -> PageResult:
        if response.status == 404 and page > 1:
            # Past the last page the shop answers 404 (the catalog can shrink during a run).
            log.debug("Page %d is past the end", page)
            return PageResult(count=0, items=(), facets=Facets(), raw='{"status": 404}')
        raise_for_status(response)
        try:
            data = extract_listing(response.text)
        except NuxtStateError as exc:
            raise ContractError(f"Unreadable page state: {exc}", raw=response.text) from exc
        if data is None:
            if any(marker in response.text for marker in _CHALLENGE_MARKERS):
                raise BlockedError("Got a bot check instead of the catalog", raw=response.text)
            raise ContractError("The page has no product listing", raw=response.text)
        return self.parse_listing(data, page)

    def parse_listing(self, data: Mapping[str, Any], page: int = 1) -> PageResult:
        """A page from what `extract_listing` took from it (also the archived format)."""
        text = json.dumps(data, ensure_ascii=False)
        try:
            listing = RawListing.model_validate(data)
        except ValidationError as exc:
            raise ContractError(f"Unexpected product listing: {short(str(exc))}", raw=text) from exc
        details = listing.listing_details
        if details.products_per_page != self.page_size:
            raise ContractError(
                f"The shop shows {details.products_per_page} items per page, not {self.page_size}",
                raw=text,
            )
        if details.current_page != page:
            log.debug("Page %d is not what the shop served (%d pages)", page, details.total_pages)
            return PageResult(count=details.total_products, items=(), facets=Facets(), raw=text)
        by_sku = {entry.get("sku"): entry for entry in listing.products_analytics}
        pairs = [
            {"id": card.get("sku"), "card": card, "details": by_sku.get(card.get("sku"))}
            for card in listing.products
        ]
        items, invalid = self._normalize_items(
            pairs,
            lambda pair: self.normalize(
                RawCard.model_validate(pair["card"]), RawDetails.model_validate(pair["details"])
            ),
            raw=text,
        )
        return PageResult(
            count=details.total_products,
            items=items,
            facets=Facets(),
            raw=text,
            invalid_items=invalid,
        )

    def root_segments(self, root: PageResult) -> list[Segment]:
        return [Segment(sex=code) for code in self.config.sections]

    def gender_of(self, segment: Segment) -> Gender:
        if segment.sex is None:
            return Gender(0)
        return self.config.sections[segment.sex].gender

    def normalize(self, card: RawCard, details: RawDetails) -> ProductRecord:
        if card.currency != self.config.currency:
            raise ValueError(f"Unexpected currency {card.currency}")
        design = card.design
        if not design.url.startswith("/p/"):
            raise ValueError(f"Unexpected product URL {design.url!r}")
        price = details.price
        current = price.promotional.amount
        regular = price.regular.amount
        if current is None:
            current = regular
        if current is None:
            raise ValueError("The item has no price")
        lowest = price.omnibus.amount
        brand = " ".join(design.brand.split())
        kind, _, rest = design.name.partition(_PARTS)
        name = " ".join(kind.split()) or " ".join(design.name.split())
        images = _images(card.main_image, design.images, self.config.image_host)
        sizes = _sizes(details.variants)
        # The shop truncates its percent (3,799 of 4,199 is 9.5%, shown as 9%): the default.
        return ProductRecord.create(
            site=self.code,
            external_id=card.sku,
            url=self.config.origin + design.url,
            name=name,
            subtitle=_subtitle(design.images, name),
            brand=BrandRef(external_id=brand, name=brand),
            color=clean(details.color) or clean(rest.partition(_PARTS)[0]),
            image=images[0] if images else None,
            gallery=images,
            categories=(),  # the listing names only the section it was loaded from
            price_minor=to_minor(current),
            price_regular_minor=to_minor(regular if regular is not None else current),
            price_min30_minor=to_minor(lowest) if lowest is not None else None,
            available_for_buy=any(s.in_stock for s in sizes) if sizes else True,
            sizes=sizes,
        )


def _subtitle(images: list[RawImage], name: str) -> str | None:
    """The rest of the item's full name: model, color and fit. The listing has it only in the
    pictures' alt text, "<brand> <brand> <name> <rest>"."""
    marker = f" {name} "
    for image in images:
        alt = " ".join((image.alt or "").split())
        _, found, rest = alt.partition(marker)
        if found:
            return rest or None
    return None


_IMAGE = re.compile(r"/[a-z_]+\(([0-9a-f](?:/[0-9a-f]){3}/[A-Za-z0-9_.-]+),[a-z]+\)(?:/|$)")


def _images(main: str | None, images: list[RawImage], host: str) -> tuple[ImageRef, ...]:
    names: list[str] = [main] if main else []
    for image in images:
        match = _IMAGE.match(image.src, len(host)) if image.src.startswith(host + "/") else None
        if match is None:
            log.debug("Ignoring an image URL of an unknown shape: %s", image.src)
            continue
        names.append(match.group(1))
    refs: list[ImageRef] = []
    for name in names:
        ref = ImageRef(name=name, version="")
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


_AVAILABILITY = {
    "plenty": "IN_STOCK",
    "enough": "IN_STOCK",
    "low": "LAST",
    "unavailable": "OUT_OF_STOCK",
}
_IN_STOCK = frozenset({"IN_STOCK", "LAST"})
_SIZE_LABELS = ("clothes_size", "footwear_size", "rozmiar_karta_produktu")
"""The size the shop's filter uses (XS, 38), else the one its product card shows, which can be
in another system (34 for a women's XS)."""


def _sizes(variants: Mapping[str, RawVariant]) -> tuple[SizeRecord, ...]:
    ordered = sorted(
        variants.items(), key=lambda kv: kv[1].sort_order if kv[1].sort_order is not None else 1e9
    )
    sizes: list[SizeRecord] = []
    for code, variant in ordered:
        label = next(
            (variant.values[key].value.label for key in _SIZE_LABELS if key in variant.values),
            variant.size or code,
        )
        availability = _AVAILABILITY.get(variant.availability, variant.availability.upper())
        sizes.append(
            SizeRecord(
                external_id=code,
                label=label.strip(),
                variation_id=variant.id or code,
                ean=None,
                availability=availability,
                in_stock=availability in _IN_STOCK,
            )
        )
    return tuple(sizes)
