"""Site-agnostic, normalized product model produced by every site adapter."""

from decimal import ROUND_DOWN
from enum import IntFlag
from typing import Self

from pydantic import BaseModel, ConfigDict

from salevault.domain.discounts import percent_off


class Gender(IntFlag):
    """Bit mask; an item seen in several gender sections gets several bits (unisex)."""

    MEN = 1
    WOMEN = 2
    HOME = 4
    KIDS = 8


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ImageRef(_Frozen):
    name: str
    version: str


class BrandRef(_Frozen):
    external_id: str
    name: str
    slug: str | None = None


class CategoryRef(_Frozen):
    external_id: str
    name: str


class CategoryNode(_Frozen):
    """A node of the shop's category tree (the source of truth for parents and depth)."""

    external_id: str
    name: str
    parent_external_id: str | None
    depth: int


class SizeRecord(_Frozen):
    external_id: str
    label: str
    variation_id: str
    ean: str | None
    availability: str
    in_stock: bool


class ProductRecord(_Frozen):
    site: str
    external_id: str
    url: str
    name: str
    subtitle: str | None
    brand: BrandRef
    color: str | None
    image: ImageRef | None
    gallery: tuple[ImageRef, ...]
    categories: tuple[CategoryRef, ...]
    """Category assignments as served: one or more root-to-leaf paths, concatenated and
    sometimes without their root. Parents come from the category tree, not from this list."""
    price_minor: int
    price_regular_minor: int
    price_min30_minor: int | None
    """Lowest price over the last 30 days, if the site publishes it."""
    available_for_buy: bool
    sizes: tuple[SizeRecord, ...]

    # Derived fields, always computed by `create`.
    discount_pct: int
    discount_min30_pct: int | None
    savings_minor: int
    search_text: str

    @classmethod
    def create(
        cls,
        *,
        site: str,
        external_id: str,
        url: str,
        name: str,
        subtitle: str | None,
        brand: BrandRef,
        color: str | None,
        image: ImageRef | None,
        gallery: tuple[ImageRef, ...],
        categories: tuple[CategoryRef, ...],
        price_minor: int,
        price_regular_minor: int,
        price_min30_minor: int | None,
        available_for_buy: bool,
        sizes: tuple[SizeRecord, ...],
        percent_rounding: str = ROUND_DOWN,
    ) -> Self:
        """`percent_rounding` is how the shop rounds its discount badges (see `percent_off`)."""
        discount_min30 = (
            percent_off(price_minor, price_min30_minor, rounding=percent_rounding)
            if price_min30_minor is not None and price_min30_minor > price_minor
            else None
        )
        return cls(
            site=site,
            external_id=external_id,
            url=url,
            name=name,
            subtitle=subtitle,
            brand=brand,
            color=color,
            image=image,
            gallery=gallery,
            categories=categories,
            price_minor=price_minor,
            price_regular_minor=price_regular_minor,
            price_min30_minor=price_min30_minor,
            available_for_buy=available_for_buy,
            sizes=sizes,
            discount_pct=percent_off(price_minor, price_regular_minor, rounding=percent_rounding),
            discount_min30_pct=discount_min30,
            savings_minor=max(price_regular_minor - price_minor, 0),
            search_text=build_search_text(brand.name, name, subtitle, color),
        )


def build_search_text(*parts: str | None) -> str:
    """Casefolded text for substring search; SQLite LIKE only folds ASCII case."""
    return " ".join(" ".join(p.split()).casefold() for p in parts if p and p.strip())
