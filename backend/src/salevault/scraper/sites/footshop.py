"""Adapter for Footshop (footshop.ua): reads the sale catalog pages themselves.

The shop's robots.txt disallows its JSON endpoints (`*/api/*`, `?ajax=`) for every user agent
and allows the catalog pages with path pagination (`/page-N`). Each catalog page carries its
product listing as JSON for the page's own scripts (server-side rendering), so one page view
gives 24 complete items. See docs/decisions/0006-reading-catalog-pages.md.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
    FacetValue,
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

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FootshopSection:
    """A gender section of the sale, as linked from the shop's own menu."""

    path: str
    gender: Gender


@dataclass(frozen=True, slots=True)
class FootshopConfig:
    code: str
    display_name: str
    origin: str
    language: str
    """Path prefix of the storefront language, e.g. "uk"."""
    sale_path: str
    """The whole sale: the start page and the source of the expected item count."""
    sections: Mapping[str, FootshopSection]
    """Gender sections of the sale; their union is the whole sale."""
    currency: str = "UAH"
    concurrency: int = 1
    headless: bool = False
    transport: TransportMode = "auto"
    image_host: str = "https://static.ftshp.digital"
    thumb_size: str = "full_product"
    """Image variants the CDN serves: `full_product` is 525 px square, `thickbox` 800 px."""
    full_size: str = "thickbox"

    def image_urls(self, name: str, version: str) -> tuple[str, str]:
        """`name` is "<image id>.<extension>"; the CDN path spells the id digit by digit."""
        image_id, _, ext = name.partition(".")
        folder = "/".join(image_id)
        base = f"{self.image_host}/img/p/{folder}/{image_id}"
        return f"{base}-{self.thumb_size}.{ext}", f"{base}-{self.full_size}.{ext}"

    @property
    def site_info(self) -> SiteInfo:
        return SiteInfo(
            code=self.code, name=self.display_name, origin=self.origin, currency=self.currency
        )


# --- Listing models (the JSON embedded in a catalog page) -------------------------------------


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, coerce_numbers_to_str=True)


class RawPrice(_Raw):
    value: Decimal
    value_without_reduction: Decimal
    currency_code: str


class RawRef(_Raw):
    id: str
    name: str


class RawVariant(_Raw):
    name: str
    url: str = ""
    ean: str | None = None
    package_id: str


class RawAttributes(_Raw):
    variants: list[RawVariant] = Field(default_factory=list)


class RawItem(_Raw):
    id: str
    url: str
    name: str
    title: str | None = None
    title_without_manufacturer: str | None = None
    price: RawPrice
    manufacturer: RawRef
    main_category: RawRef | None = None
    color: str | None = None
    image: str | None = None
    image_woman: str | None = None
    last_image: str | None = None
    in_stock: bool = True
    sold_out: bool = False
    upcoming: Any = None
    attributes: RawAttributes = Field(default_factory=RawAttributes)

    @field_validator("attributes", mode="before")
    @classmethod
    def _empty_list_is_empty_object(cls, value: object) -> object:
        return {} if value == [] else value  # the backend encodes an empty map as []


class RawPagination(_Raw):
    page: int
    total_pages: int
    items_per_page: int


class RawProducts(_Raw):
    total: int
    items: list[dict[str, Any]]
    pagination: RawPagination


class RawState(_Raw):
    products: RawProducts
    filters: dict[str, Any] = Field(default_factory=dict)


class RawListingData(_Raw):
    state: RawState


class RawListing(_Raw):
    data: RawListingData


class RawFacetItem(_Raw):
    id: str
    name: str
    count: int = 0


class RawChoiceFacet(_Raw):
    items: list[RawFacetItem]


_LISTING = re.compile(
    r'<script[^>]*data-hypernova-key="ProductListing"[^>]*><!--(.*?)--></script>', re.DOTALL
)
_IMAGE = re.compile(r"/img/p/(?:\d/)+(\d+)-[a-z_]+\.([a-z]+)$")
_SIZE_PARAM = re.compile(r"[?&]size=(\d+)")
_CHALLENGE_MARKERS = ("challenge-platform", "cf-chl", "cf_chl_opt", "Just a moment...")
"""Signs of a bot check page served with status 200; normal catalog pages have none of them."""


def extract_listing(html: str) -> str | None:
    """The JSON of the page's product listing, or None if the page has none.

    The page embeds it in an HTML comment with `&` and `>` escaped (Hypernova's encoding)."""
    match = _LISTING.search(html)
    if match is None:
        return None
    return match.group(1).replace("&gt;", ">").replace("&amp;", "&")


# --- Adapter ---------------------------------------------------------------------------------


class FootshopAdapter:
    page_size = 24
    max_pages = 2000
    """No cap seen: the last page of the whole sale (page 634 of 634) is served. This limit only
    guards against a runaway plan."""

    def __init__(self, config: FootshopConfig, transport: Transport) -> None:
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
        if segment.price is not None:
            raise ValueError("Footshop segments cannot be filtered by price")
        if segment.sex is None:
            path = self.config.sale_path
        else:
            path = self.config.sections[segment.sex].path
        if page > 1:
            path = f"{path}/page-{page}"
        return self.config.origin + path

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        if segment == Segment() and page == 1 and self._start_page is not None:
            response, self._start_page = self._start_page, None
        else:
            response = await self._transport.get(self.page_url(segment, page))
        return self.parse_page(response, page)

    def parse_page(self, response: HttpResponse, page: int = 1) -> PageResult:
        raise_for_status(response)
        text = extract_listing(response.text)
        if text is None:
            if any(marker in response.text for marker in _CHALLENGE_MARKERS):
                raise BlockedError("Got a bot check instead of the catalog", raw=response.text)
            raise ContractError("The page has no product listing", raw=response.text)
        try:
            listing = RawListing.model_validate_json(text)
        except ValidationError as exc:
            raise ContractError(f"Unexpected product listing: {short(str(exc))}", raw=text) from exc
        products = listing.data.state.products
        if products.pagination.page != page:
            # Past the end the shop serves its last page again (the catalog can shrink during a
            # run); those items were already counted, so this page is empty.
            log.debug("Page %d is past the end (%d pages)", page, products.pagination.total_pages)
            return PageResult(count=products.total, items=(), facets=Facets(), raw=text)
        items, invalid = self._normalize_items(
            products.items, lambda item: self.normalize(RawItem.model_validate(item)), raw=text
        )
        return PageResult(
            count=products.total,
            items=items,
            facets=_parse_facets(listing.data.state.filters),
            raw=text,
            invalid_items=invalid,
        )

    def root_segments(self, root: PageResult) -> list[Segment]:
        return [Segment(sex=code) for code in self.config.sections]

    def gender_of(self, segment: Segment) -> Gender:
        if segment.sex is None:
            return Gender(0)
        return self.config.sections[segment.sex].gender

    def normalize(self, raw: RawItem) -> ProductRecord:
        if raw.price.currency_code != self.config.currency:
            raise ValueError(f"Unexpected currency {raw.price.currency_code}")
        title = clean(raw.title) or raw.name.strip()
        rest = raw.name.strip()[len(title) :] if raw.name.strip().startswith(title) else ""
        available = raw.in_stock and not raw.sold_out and not raw.upcoming
        images = _images(raw.image, raw.image_woman, raw.last_image)
        return ProductRecord.create(
            site=self.code,
            external_id=raw.id,
            url=f"{self.config.origin}/{self.config.language}/{raw.url.lstrip('/')}",
            name=clean(raw.title_without_manufacturer) or title,
            subtitle=clean(rest),
            brand=BrandRef(external_id=raw.manufacturer.id, name=raw.manufacturer.name.strip()),
            color=clean(raw.color),
            image=images[0] if images else None,
            gallery=images,
            categories=(
                (CategoryRef(external_id=raw.main_category.id, name=raw.main_category.name),)
                if raw.main_category is not None
                else ()
            ),
            price_minor=to_minor(raw.price.value),
            price_regular_minor=to_minor(raw.price.value_without_reduction),
            price_min30_minor=None,
            available_for_buy=available,
            percent_rounding=ROUND_HALF_UP,  # the shop's badges round: 9.99% is "-10 %"
            sizes=tuple(
                SizeRecord(
                    external_id=_size_id(v),
                    label=v.name.strip(),
                    variation_id=v.package_id,
                    ean=v.ean or None,
                    # The listing shows the sizes that can be bought now.
                    availability="IN_STOCK" if available else "OUT_OF_STOCK",
                    in_stock=available,
                )
                for v in raw.attributes.variants
            ),
        )


def _images(*urls: str | None) -> tuple[ImageRef, ...]:
    refs: list[ImageRef] = []
    for url in urls:
        match = _IMAGE.search(url or "")
        if match is None:
            if url:
                log.debug("Ignoring an image URL of an unknown shape: %s", url)
            continue
        ref = ImageRef(name=f"{match.group(1)}.{match.group(2)}", version="")
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _size_id(variant: RawVariant) -> str:
    match = _SIZE_PARAM.search(variant.url)
    return match.group(1) if match else variant.package_id


def _parse_facets(filters: dict[str, Any]) -> Facets:
    sex = filters.get("sex")
    if not isinstance(sex, dict):
        return Facets()
    try:
        facet = RawChoiceFacet.model_validate(sex)
    except ValidationError as exc:
        log.warning("Ignoring a malformed sex facet: %s", short(str(exc)))
        return Facets()
    return Facets(sex=tuple(FacetValue(i.id, i.name, i.count) for i in facet.items))
