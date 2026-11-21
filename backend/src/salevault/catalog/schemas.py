"""Request and response models of the catalog API. Prices are whole currency units."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_ID = 2**63 - 1
"""Largest integer SQLite stores; bigger ids or prices would overflow the driver (HTTP 500)."""
MAX_PRICE = 100_000_000
"""Whole currency units; far above any real price and far below an integer overflow."""
Id = Annotated[int, Field(ge=1, le=MAX_ID)]
CategorySlug = Annotated[str, Field(pattern=r"^[a-z]+(\.[a-z]+)?$", max_length=64)]
BrandKey = Annotated[str, Field(pattern=r"^[\w-]+$", max_length=255)]
"""A brand across shops: its name casefolded, words joined with "-" (`domain/brands.py`)."""
"""A group (`clothing`) or a leaf (`clothing.jackets`) of the shared category tree."""


GenderCode = Literal["men", "women", "home", "kids"]
Flag = Literal["new", "price_drop", "favorite"]
Badge = Literal["new", "price_drop"]
Sort = Literal[
    "discount_desc",
    "discount_min30_desc",
    "savings_desc",
    "price_asc",
    "price_desc",
    "newest",
]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- queries -----------------------------------------------------------------------------------


class CatalogQuery(BaseModel):
    """Filters shared by the product list and the facets."""

    model_config = ConfigDict(extra="forbid")

    site: list[str] = Field(default_factory=list, max_length=20, description="Site codes, e.g. prm")
    gender: list[GenderCode] = Field(default_factory=list, max_length=4)
    category: list[CategorySlug] = Field(
        default_factory=list,
        max_length=100,
        description="Shared categories: a group matches all of its leaves",
    )
    brand: list[BrandKey] = Field(
        default_factory=list, max_length=500, description="Brand keys; one key covers every shop"
    )
    size: list[str] = Field(
        default_factory=list, max_length=200, description="Size labels in stock"
    )
    my_sizes: bool = Field(False, description="Only items with one of my sizes in stock")
    price_min: int | None = Field(None, ge=0, le=MAX_PRICE)
    price_max: int | None = Field(None, ge=0, le=MAX_PRICE)
    discount_min: int | None = Field(None, ge=0, le=100)
    discount_max: int | None = Field(None, ge=0, le=100)
    q: str | None = Field(None, max_length=100, description="Words to find in brand or name")
    flags: list[Flag] = Field(default_factory=list)
    include_inactive: bool = Field(False, description="Also items that left the sale")


class FacetsQuery(CatalogQuery):
    heavy: bool = Field(
        True,
        description="Also count sizes (the slow part on big catalogs). "
        "The UI asks for heavy=false first so the cheap facets show up at once.",
    )


class ProductsQuery(CatalogQuery):
    sort: Sort = "discount_desc"
    page: int = Field(1, ge=1, le=100_000)
    page_size: int = Field(60, ge=1, le=120)


# --- products ----------------------------------------------------------------------------------


class BrandOut(_Out):
    id: int
    name: str


class ImageOut(_Out):
    thumb: str
    full: str


class SizeOut(_Out):
    label: str
    in_stock: bool
    is_mine: bool


class ProductCard(_Out):
    id: int
    site: str
    url: str
    brand: BrandOut
    name: str
    subtitle: str | None
    color: str | None
    image: ImageOut | None
    price: int
    price_regular: int
    price_min30: int | None
    currency: str
    discount_pct: int
    discount_min30_pct: int | None
    savings: int
    prev_price: int | None
    badges: list[Badge]
    genders: list[GenderCode]
    sizes: list[SizeOut]
    is_favorite: bool
    is_active: bool
    first_seen_at: datetime


class ProductPage(_Out):
    items: list[ProductCard]
    total: int
    page: int
    page_size: int


class CategoryOut(_Out):
    id: int
    name: str


class SizeDetail(SizeOut):
    variation_id: str = Field(description="Unique per product; labels may repeat")
    availability: str


class HistoryPoint(_Out):
    observed_at: datetime
    price: int
    price_regular: int
    price_min30: int | None
    discount_pct: int


class ProductDetail(ProductCard):
    gallery: list[ImageOut]
    category_paths: list[list[CategoryOut]]
    """Root-to-leaf paths, one per most specific category (unisex items have several)."""
    size_details: list[SizeDetail]
    price_history: list[HistoryPoint]
    last_seen_at: datetime


# --- facets ------------------------------------------------------------------------------------


class ValueCount(_Out):
    value: str
    label: str
    count: int


class BrandFacet(_Out):
    id: str = Field(description="Brand key, the same in every shop")
    name: str
    count: int


class CategoryFacet(_Out):
    id: str = Field(description="Slug of the shared category tree")
    name: str
    parent_id: str | None
    depth: int
    count: int


class SizeFacet(_Out):
    label: str
    count: int


class Range(_Out):
    min: int | None
    max: int | None


class Facets(_Out):
    total: int
    sites: list[ValueCount]
    genders: list[ValueCount]
    categories: list[CategoryFacet]
    """The shared category tree in its own order, only nodes with items."""
    brands: list[BrandFacet]
    sizes: list[SizeFacet] | None
    price: Range
    discount: Range


# --- favorites and settings --------------------------------------------------------------------


class FavoriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, max_length=500)


class FavoriteOut(_Out):
    product: ProductCard
    added_at: datetime
    price_at_add: int
    price_change: int
    """Current price minus the price when it was added (negative = cheaper)."""
    note: str | None


class SettingsOut(_Out):
    my_sizes: list[str]


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    my_sizes: list[str] | None = Field(None, max_length=100)


GENDER_BITS: Mapping[GenderCode, int] = {"men": 1, "women": 2, "home": 4, "kids": 8}
GENDER_LABELS: Mapping[GenderCode, str] = {
    "men": "Men",
    "women": "Women",
    "home": "Home",
    "kids": "Kids",
}
