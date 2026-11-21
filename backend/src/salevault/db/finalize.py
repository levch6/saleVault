"""Merge a run's staged items into the catalog in one transaction (ADR-0004)."""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from salevault.db.models import (
    Brand,
    Category,
    PriceHistory,
    Product,
    ProductCategory,
    ProductSize,
    RunItem,
    RunPage,
    ScrapeRun,
)
from salevault.db.types import utcnow
from salevault.domain.models import ProductRecord

MISSES_BEFORE_INACTIVE = 2
"""Consecutive successful runs without an item before it is considered gone (ADR-0004)."""


@dataclass(frozen=True, slots=True)
class RunStats:
    seen: int
    new: int
    price_drops: int
    price_ups: int
    returned: int
    """Inactive items that showed up again."""
    missing: int
    """Active items not seen this time, still within the grace period."""
    removed: int
    """Items deactivated by this run."""

    def to_json(self) -> dict[str, int]:
        return asdict(self)


def finalize_run(
    session: Session, run_id: int, *, deactivate: bool, now: datetime | None = None
) -> RunStats:
    """Merge staging into products, sizes, categories and the price change log.

    `deactivate` is only true for successful runs: partial runs never count misses.
    """
    now = now or utcnow()
    run = session.get_one(ScrapeRun, run_id)
    site_id = run.site_id

    staged: dict[str, tuple[ProductRecord, int]] = {}
    for external_id, mask, record_json in session.execute(
        select(RunItem.external_id, RunItem.gender_mask, RunItem.record_json).where(
            RunItem.run_id == run_id
        )
    ):
        staged[external_id] = (ProductRecord.model_validate_json(record_json), mask)
    records = [record for record, _ in staged.values()]

    brand_ids = _upsert_brands(session, site_id, records)
    category_ids = _upsert_categories(session, site_id, records)

    existing = {
        row.external_id: row
        for row in session.execute(
            select(
                Product.id,
                Product.external_id,
                Product.price_minor,
                Product.price_regular_minor,
                Product.price_min30_minor,
                Product.is_active,
            ).where(Product.site_id == site_id)
        )
    }

    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    changed: set[str] = set()
    new = price_drops = price_ups = returned = 0
    for external_id, (record, mask) in staged.items():
        values = _product_values(record, mask, brand_ids[record.brand.external_id])
        values |= {"last_seen_at": now, "last_seen_run_id": run_id, "is_active": True}
        values["missed_runs"] = 0
        old = existing.get(external_id)
        if old is None:
            new += 1
            changed.add(external_id)
            inserts.append(
                values
                | {
                    "site_id": site_id,
                    "external_id": external_id,
                    "first_seen_at": now,
                    "first_seen_run_id": run_id,
                }
            )
            continue

        if not old.is_active:
            returned += 1
        if record.price_minor != old.price_minor:
            values["prev_price_minor"] = old.price_minor
            values["last_price_change_run_id"] = run_id
            if record.price_minor < old.price_minor:
                price_drops += 1
            else:
                price_ups += 1
        if (record.price_minor, record.price_regular_minor, record.price_min30_minor) != (
            old.price_minor,
            old.price_regular_minor,
            old.price_min30_minor,
        ):
            changed.add(external_id)
        updates.append(values | {"id": old.id})

    if inserts:
        session.execute(insert(Product), inserts)
    if updates:
        session.execute(update(Product), updates)

    product_ids = _id_map(session, Product, site_id)

    history = [
        {
            "product_id": product_ids[external_id],
            "run_id": run_id,
            "observed_at": now,
            "price_minor": staged[external_id][0].price_minor,
            "price_regular_minor": staged[external_id][0].price_regular_minor,
            "price_min30_minor": staged[external_id][0].price_min30_minor,
            "discount_pct": staged[external_id][0].discount_pct,
        }
        for external_id in changed
    ]
    if history:
        session.execute(insert(PriceHistory), history)

    _replace_children(session, site_id, run_id, staged, product_ids, category_ids)

    missing = removed = 0
    if deactivate:
        missing, removed = _count_misses(session, site_id, run_id)

    session.execute(delete(RunItem).where(RunItem.run_id == run_id))
    session.execute(delete(RunPage).where(RunPage.run_id == run_id))
    return RunStats(
        seen=len(staged),
        new=new,
        price_drops=price_drops,
        price_ups=price_ups,
        returned=returned,
        missing=missing,
        removed=removed,
    )


def _id_map(
    session: Session, model: type[Brand] | type[Category] | type[Product], site_id: int
) -> dict[str, int]:
    """external_id -> id for one site."""
    rows = session.execute(select(model.external_id, model.id).where(model.site_id == site_id))
    # Not dict(rows): Result has .keys(), so dict() would treat it as a mapping.
    return {external_id: row_id for external_id, row_id in rows}  # noqa: C416


def _product_values(record: ProductRecord, mask: int, brand_id: int) -> dict[str, Any]:
    return {
        "url": record.url,
        "brand_id": brand_id,
        "name": record.name,
        "subtitle": record.subtitle,
        "color": record.color,
        "gender_mask": mask,
        "image_name": record.image.name if record.image else None,
        "image_version": record.image.version if record.image else None,
        "gallery_json": json.dumps([[i.name, i.version] for i in record.gallery]),
        "price_minor": record.price_minor,
        "price_regular_minor": record.price_regular_minor,
        "price_min30_minor": record.price_min30_minor,
        "discount_pct": record.discount_pct,
        "discount_min30_pct": record.discount_min30_pct,
        "savings_minor": record.savings_minor,
        "available_for_buy": record.available_for_buy,
        "search_text": record.search_text,
    }


def _upsert_brands(
    session: Session, site_id: int, records: Iterable[ProductRecord]
) -> dict[str, int]:
    brands = {r.brand.external_id: r.brand for r in records}
    if brands:
        stmt = sqlite_insert(Brand).values(
            [
                {"site_id": site_id, "external_id": b.external_id, "name": b.name, "slug": b.slug}
                for b in brands.values()
            ]
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Brand.site_id, Brand.external_id],
                set_={"name": stmt.excluded.name, "slug": stmt.excluded.slug},
            )
        )
    return _id_map(session, Brand, site_id)


def _upsert_categories(
    session: Session, site_id: int, records: Iterable[ProductRecord]
) -> dict[str, int]:
    nodes: dict[str, tuple[str, str | None, int]] = {}  # external_id -> (name, parent, depth)
    for record in records:
        parent: str | None = None
        for depth, category in enumerate(record.categories):
            nodes.setdefault(category.external_id, (category.name, parent, depth))
            parent = category.external_id
    if nodes:
        stmt = sqlite_insert(Category).values(
            [
                {"site_id": site_id, "external_id": ext, "name": name, "depth": depth}
                for ext, (name, _parent, depth) in nodes.items()
            ]
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Category.site_id, Category.external_id],
                set_={"name": stmt.excluded.name, "depth": stmt.excluded.depth},
            )
        )
    ids = _id_map(session, Category, site_id)
    parents = [
        {"id": ids[ext], "parent_id": ids[parent] if parent else None}
        for ext, (_name, parent, _depth) in nodes.items()
    ]
    if parents:
        session.execute(update(Category), parents)
    return ids


def _replace_children(
    session: Session,
    site_id: int,
    run_id: int,
    staged: dict[str, tuple[ProductRecord, int]],
    product_ids: dict[str, int],
    category_ids: dict[str, int],
) -> None:
    seen = select(Product.id).where(Product.site_id == site_id, Product.last_seen_run_id == run_id)
    session.execute(delete(ProductSize).where(ProductSize.product_id.in_(seen)))
    session.execute(delete(ProductCategory).where(ProductCategory.product_id.in_(seen)))

    sizes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for external_id, (record, _mask) in staged.items():
        product_id = product_ids[external_id]
        variations: set[str] = set()
        for size in record.sizes:
            if size.variation_id in variations:
                continue
            variations.add(size.variation_id)
            sizes.append(
                {
                    "product_id": product_id,
                    "variation_id": size.variation_id,
                    "size_external_id": size.external_id,
                    "label": size.label,
                    "ean": size.ean,
                    "availability": size.availability,
                    "in_stock": size.in_stock,
                }
            )
        for category_id in {category_ids[c.external_id] for c in record.categories}:
            links.append({"product_id": product_id, "category_id": category_id})
    if sizes:
        session.execute(insert(ProductSize), sizes)
    if links:
        session.execute(insert(ProductCategory), links)


def _count_misses(session: Session, site_id: int, run_id: int) -> tuple[int, int]:
    """Bump `missed_runs` of active items this run did not see; deactivate after the grace."""
    rows = session.execute(
        select(Product.id, Product.missed_runs).where(
            Product.site_id == site_id,
            Product.is_active.is_(True),
            Product.last_seen_run_id != run_id,
        )
    ).all()
    changes = []
    removed = 0
    for product_id, missed in rows:
        missed += 1
        gone = missed >= MISSES_BEFORE_INACTIVE
        removed += gone
        changes.append({"id": product_id, "missed_runs": missed, "is_active": not gone})
    if changes:
        session.execute(update(Product), changes)
    return len(rows) - removed, removed
