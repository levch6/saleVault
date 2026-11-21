"""SQL conditions for catalog filters. Facets drop their own filter via `skip`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, and_, exists, false, or_, select
from sqlalchemy.orm import Session

from salevault.catalog.schemas import GENDER_BITS, CatalogQuery
from salevault.db.models import Favorite, Product, ProductCategory, ProductSize, ScrapeRun

FacetName = Literal["site", "gender", "category", "brand", "size", "price", "discount"]
FINISHED = ("success", "partial")


@dataclass(frozen=True, slots=True)
class SiteRuns:
    latest_run_id: int
    """Latest finished (success or partial) run: the reference for New / Price drop."""
    has_previous: bool
    """False on the very first run, so that it doesn't mark the whole catalog as new."""


RunContext = Mapping[int, SiteRuns]


def load_run_context(session: Session) -> dict[int, SiteRuns]:
    rows = session.execute(
        select(ScrapeRun.site_id, ScrapeRun.id)
        .where(ScrapeRun.status.in_(FINISHED))
        .order_by(ScrapeRun.site_id, ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
    )
    context: dict[int, SiteRuns] = {}
    for site_id, run_id in rows:
        if site_id not in context:
            context[site_id] = SiteRuns(latest_run_id=run_id, has_previous=False)
        else:
            context[site_id] = SiteRuns(context[site_id].latest_run_id, has_previous=True)
    return context


def is_new(first_seen_run_id: int, site_id: int, runs: RunContext) -> bool:
    info = runs.get(site_id)
    return info is not None and info.has_previous and first_seen_run_id == info.latest_run_id


def is_price_drop(
    last_change_run_id: int | None,
    price_minor: int,
    prev_price_minor: int | None,
    site_id: int,
    runs: RunContext,
) -> bool:
    info = runs.get(site_id)
    return (
        info is not None
        and last_change_run_id == info.latest_run_id
        and prev_price_minor is not None
        and price_minor < prev_price_minor
    )


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True)
class CatalogFilter:
    query: CatalogQuery
    site_ids: Sequence[int]
    """Resolved from `query.site`; an unknown code resolves to no ids (matches nothing)."""
    my_sizes: Sequence[str]
    runs: RunContext

    def conditions(self, *, skip: FacetName | None = None) -> list[ColumnElement[bool]]:
        q = self.query
        conds: list[ColumnElement[bool]] = []
        if not q.include_inactive:
            conds.append(Product.is_active.is_(True))
        if q.site and skip != "site":
            conds.append(Product.site_id.in_(self.site_ids))
        if q.gender and skip != "gender":
            mask = sum(GENDER_BITS[g] for g in set(q.gender))
            conds.append(Product.gender_mask.op("&")(mask) != 0)
        if q.brand and skip != "brand":
            conds.append(Product.brand_id.in_(q.brand))
        if q.category and skip != "category":
            conds.append(
                exists().where(
                    ProductCategory.product_id == Product.id,
                    ProductCategory.category_id.in_(q.category),
                )
            )
        if q.size and skip != "size":
            conds.append(_has_size_in_stock(q.size))
        if q.my_sizes and self.my_sizes:
            conds.append(_has_size_in_stock(self.my_sizes))
        if skip != "price":
            if q.price_min is not None:
                conds.append(Product.price_minor >= q.price_min * 100)
            if q.price_max is not None:
                conds.append(Product.price_minor <= q.price_max * 100)
        if skip != "discount":
            if q.discount_min is not None:
                conds.append(Product.discount_pct >= q.discount_min)
            if q.discount_max is not None:
                conds.append(Product.discount_pct <= q.discount_max)
        if q.q:
            for word in q.q.casefold().split():
                conds.append(Product.search_text.like(f"%{escape_like(word)}%", escape="\\"))
        for flag in set(q.flags):
            if flag == "new":
                conds.append(self._new())
            elif flag == "price_drop":
                conds.append(self._price_drop())
            else:
                conds.append(exists().where(Favorite.product_id == Product.id))
        return conds

    def _new(self) -> ColumnElement[bool]:
        parts = [
            and_(Product.site_id == site_id, Product.first_seen_run_id == info.latest_run_id)
            for site_id, info in self.runs.items()
            if info.has_previous
        ]
        return or_(*parts) if parts else false()

    def _price_drop(self) -> ColumnElement[bool]:
        parts = [
            and_(
                Product.site_id == site_id,
                Product.last_price_change_run_id == info.latest_run_id,
                Product.price_minor < Product.prev_price_minor,
            )
            for site_id, info in self.runs.items()
        ]
        return or_(*parts) if parts else false()


def _has_size_in_stock(labels: Sequence[str]) -> ColumnElement[bool]:
    return exists().where(
        ProductSize.product_id == Product.id,
        ProductSize.in_stock.is_(True),
        ProductSize.label.in_(labels),
    )
