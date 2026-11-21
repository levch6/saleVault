"""Adapter for shops on the Answear platform (PRM.com, Answear.ua): `POST <base>/api/products`."""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

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
)
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AnswearPlatformConfig:
    code: str
    display_name: str
    origin: str
    base_path: str
    """Locale prefix of the storefront, e.g. "/ua" for PRM, "" for Answear.ua."""
    warmup_path: str
    locale: str = "uk_UA"
    currency: str = "UAH"
    api_version: str = "4.10"
    concurrency: int = 1
    headless: bool = True
    """Akamai rejects the headless shell on some shops; those use a visible window (WSLg)."""
    sort: str = ""
    """API sort used for pagination: "" (popularity), "date_desc", "price_asc", "price_desc".

    The API orders ties differently between requests, so items at page boundaries get shuffled.
    Popularity has the fewest ties: on PRM sex=D it missed 7 of 9,121 items vs 54 with price_asc
    (experiment 2026-11-21).
    """
    sex_genders: Mapping[str, Gender] = field(
        default_factory=lambda: {
            "M": Gender.MEN,
            "D": Gender.WOMEN,
            "H": Gender.HOME,
        }
    )
    in_stock_values: frozenset[str] = frozenset({"IN_STOCK", "LAST"})

    @property
    def products_path(self) -> str:
        return f"{self.base_path}/api/products"

    @property
    def site_info(self) -> SiteInfo:
        return SiteInfo(
            code=self.code, name=self.display_name, origin=self.origin, currency=self.currency
        )


# --- API response models (camelCase on the wire) -----------------------------------------


class _Api(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        coerce_numbers_to_str=True,
    )


class RawVariation(_Api):
    id: str
    ean: str | None = None
    availability: str


class RawSize(_Api):
    id: str
    name: str
    variation: RawVariation


class RawImage(_Api):
    name: str
    version: str


class RawImages(_Api):
    main_image: RawImage | None = None
    gallery_images: list[RawImage] = Field(default_factory=list)


class RawCategory(_Api):
    id: str
    name: str


class RawBrand(_Api):
    id: str
    name: str
    slug: str | None = None


class RawColor(_Api):
    name: str | None = None


class RawProduct(_Api):
    id: str
    url: str
    name: str
    subtitle: str | None = None
    available_for_buy: bool = True
    price: Decimal
    price_regular: Decimal
    price_minimal: Decimal | None = None
    all_sizes: list[RawSize] = Field(default_factory=list)
    product_images: RawImages = Field(default_factory=RawImages)
    categories: list[RawCategory] = Field(default_factory=list)
    product_brand: RawBrand
    color: RawColor | None = None


class RawFilterItem(_Api):
    value: str
    label: str
    product_count: int = 0


class RawChoiceFilter(_Api):
    name: str
    items: list[RawFilterItem]


class RawRange(_Api):
    range_min: Decimal | None = None
    range_max: Decimal | None = None


class RawRangeFilter(_Api):
    name: str
    items: RawRange


class RawProductsPage(_Api):
    count: int
    items: list[dict[str, Any]]
    filters: list[dict[str, Any]] = Field(default_factory=list)


# --- Adapter ---------------------------------------------------------------------------------


class AnswearPlatformAdapter:
    page_size = 80
    max_pages = 125

    def __init__(self, config: AnswearPlatformConfig, transport: Transport) -> None:
        self.config = config
        self.code = config.code
        self._transport = transport
        self._warned_invalid = False

    @property
    def headers(self) -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-tamago-api-version": self.config.api_version,
            "x-tamago-app": "frontApp",
            "x-tamago-locale": self.config.locale,
        }

    def request_body(self, segment: Segment, page: int) -> dict[str, object]:
        filters: dict[str, object] = {}
        if segment.sex is not None:
            filters["sex"] = [segment.sex]  # must be an array; a bare string is ignored
        if segment.price is not None:
            filters["price"] = {"min": segment.price[0], "max": segment.price[1]}
        return {
            "sort": self.config.sort,
            "filters": filters,
            "productsPerPage": self.page_size,
            "category": "",
            "page": page,
            "urlParams": "",
            "categoryTreeRequired": False,
            "sale": 1,
        }

    async def warm_up(self) -> None:
        url = self.config.origin + self.config.warmup_path
        try:
            status = await self._transport.open(url)
        except Exception as exc:  # navigation timeouts, DNS, browser errors
            raise ScrapeError(f"Could not open {url}: {exc}") from exc
        if status in (403, 429):
            raise BlockedError(f"Warm-up page {url} returned HTTP {status}")
        if status >= 400 or status == 0:
            raise ScrapeError(f"Warm-up page {url} returned HTTP {status}")

    async def fetch_page(self, segment: Segment, page: int) -> PageResult:
        response = await self._transport.post_json(
            self.config.products_path, self.request_body(segment, page), self.headers
        )
        return self.parse_page(response)

    def parse_page(self, response: HttpResponse) -> PageResult:
        _raise_for_status(response)
        try:
            envelope = RawProductsPage.model_validate_json(response.text)
        except ValidationError as exc:
            if response.text.lstrip().startswith("<"):
                raise BlockedError("Got an HTML page instead of JSON") from exc
            raise ContractError(f"Unexpected products response: {exc}") from exc

        items: list[ProductRecord] = []
        invalid = 0
        for raw_item in envelope.items:
            try:
                items.append(self.normalize(RawProduct.model_validate(raw_item)))
            except ValidationError as exc:
                invalid += 1
                if not self._warned_invalid:
                    self._warned_invalid = True
                    log.warning(
                        "Skipping invalid item %s: %s", raw_item.get("id"), _short(str(exc))
                    )
        return PageResult(
            count=envelope.count,
            items=tuple(items),
            facets=_parse_facets(envelope.filters),
            raw=response.text,
            invalid_items=invalid,
        )

    def root_segments(self, root: PageResult) -> list[Segment]:
        segments = []
        for value in root.facets.sex:
            if value.count <= 0:
                continue
            if value.code not in self.config.sex_genders:
                log.warning(
                    "Unknown gender section %r (%s); scraping it untagged", value.code, value.label
                )
            segments.append(Segment(sex=value.code))
        return segments

    def gender_of(self, segment: Segment) -> Gender:
        if segment.sex is None:
            return Gender(0)
        return self.config.sex_genders.get(segment.sex, Gender(0))

    def normalize(self, raw: RawProduct) -> ProductRecord:
        images = raw.product_images
        return ProductRecord.create(
            site=self.code,
            external_id=raw.id,
            url=f"{self.config.origin}{self.config.base_path}{raw.url}",
            name=raw.name.strip(),
            subtitle=_clean(raw.subtitle),
            brand=BrandRef(
                external_id=raw.product_brand.id,
                name=raw.product_brand.name.strip(),
                slug=raw.product_brand.slug,
            ),
            color=_clean(raw.color.name) if raw.color is not None else None,
            image=_image(images.main_image),
            gallery=tuple(ImageRef(name=i.name, version=i.version) for i in images.gallery_images),
            categories=tuple(CategoryRef(external_id=c.id, name=c.name) for c in raw.categories),
            price_minor=to_minor(raw.price),
            price_regular_minor=to_minor(raw.price_regular),
            price_min30_minor=to_minor(raw.price_minimal) if raw.price_minimal else None,
            available_for_buy=raw.available_for_buy,
            sizes=tuple(
                SizeRecord(
                    external_id=s.id,
                    label=s.name.strip(),
                    variation_id=s.variation.id,
                    ean=s.variation.ean or None,
                    availability=s.variation.availability,
                    in_stock=s.variation.availability in self.config.in_stock_values,
                )
                for s in raw.all_sizes
            ),
        )


def _raise_for_status(response: HttpResponse) -> None:
    status = response.status
    if status == 200:
        return
    if status == 0 or status >= 500:
        raise TransientError(f"HTTP {status}: {_short(response.text)}")
    if status in (403, 429):
        raise BlockedError(f"HTTP {status}")
    raise ContractError(f"HTTP {status}: {_short(response.text)}")


def _parse_facets(filters: list[dict[str, Any]]) -> Facets:
    sex: tuple[FacetValue, ...] = ()
    price_range: tuple[int, int] | None = None
    for raw in filters:
        try:
            if raw.get("name") == "sex":
                choice = RawChoiceFilter.model_validate(raw)
                sex = tuple(FacetValue(i.value, i.label, i.product_count) for i in choice.items)
            elif raw.get("name") == "price":
                rng = RawRangeFilter.model_validate(raw).items
                if rng.range_min is not None and rng.range_max is not None:
                    price_range = (math.floor(rng.range_min), math.ceil(rng.range_max))
        except ValidationError as exc:
            log.warning("Ignoring malformed %r facet: %s", raw.get("name"), _short(str(exc)))
    return Facets(sex=sex, price_range=price_range)


def _image(raw: RawImage | None) -> ImageRef | None:
    return ImageRef(name=raw.name, version=raw.version) if raw is not None else None


def _clean(text: str | None) -> str | None:
    return text.strip() or None if text is not None else None


def _short(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."
