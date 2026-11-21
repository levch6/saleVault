"""SQL conditions for catalog filters. Facets drop their own filter via `skip`."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import ColumnElement, and_, exists, false, func, select
from sqlalchemy.orm import Session, aliased

from salevault.catalog.schemas import GENDER_BITS, CatalogQuery
from salevault.db.models import Brand, Favorite, Product, ProductSize, ScrapeRun
from salevault.domain.taxonomy import leaves_of

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
    flag_ids: Mapping[str, Sequence[int]] = field(default_factory=dict)
    """Pre-resolved ids for the New / Price drop flags (see `flag_condition`)."""

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
            conds.append(Product.brand_id.in_(select(Brand.id).where(Brand.name_key.in_(q.brand))))
        if q.category and skip != "category":
            conds.append(Product.category_slug.in_(leaves_of(q.category)))
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
            if flag in self.flag_ids:
                conds.append(_id_in(self.flag_ids[flag]))
            elif flag == "favorite":
                conds.append(exists().where(Favorite.product_id == Product.id))
            else:
                conds.append(self.flag_condition(flag))
        return conds

    # Run ids are global, so "first seen in its site's latest run" is just an IN over those
    # ids: an index lookup instead of an OR per site that SQLite cannot index (205 -> ~15 ms).
    def flag_condition(self, flag: str) -> ColumnElement[bool]:
        """New / Price drop match few items; resolving them to ids first keeps SQLite from
        walking the whole discount index in search of them (200 -> ~15 ms at 160k items)."""
        return self._new() if flag == "new" else self._price_drop()

    def _new(self) -> ColumnElement[bool]:
        runs = [info.latest_run_id for info in self.runs.values() if info.has_previous]
        return Product.first_seen_run_id.in_(runs) if runs else false()

    def _price_drop(self) -> ColumnElement[bool]:
        runs = [info.latest_run_id for info in self.runs.values()]
        if not runs:
            return false()
        return and_(
            Product.last_price_change_run_id.in_(runs),
            Product.price_minor < Product.prev_price_minor,
        )


def _id_in(ids: Sequence[int]) -> ColumnElement[bool]:
    """`Product.id IN ids` with the ids bound as one JSON value: SQLite allows only 32,766
    variables per statement, and a big run can mark more items new or cheaper than that."""
    values = func.json_each(json.dumps(list(ids))).table_valued("value")
    return Product.id.in_(select(values.c.value))


def _has_size_in_stock(labels: Sequence[str]) -> ColumnElement[bool]:
    # An alias, so the subquery still works when the outer query joins product_sizes itself
    # (the size facet): otherwise auto-correlation leaves the EXISTS without a FROM.
    size = aliased(ProductSize)
    return exists().where(
        size.product_id == Product.id,
        size.in_stock.is_(True),
        size.label.in_(labels),
    )
