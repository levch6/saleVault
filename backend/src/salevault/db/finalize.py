"""Merge a run's staged items into the catalog in one transaction (ADR-0004).

Staged items are streamed in chunks (keyset pagination over `run_items`) so memory stays flat
whatever the catalog size: about 200k items finalize in well under 1 GB.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from salevault.db.categorize import path_names, recompute_depths
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
from salevault.domain.brands import brand_key
from salevault.domain.models import BrandRef, CategoryNode, CategoryRef, ProductRecord
from salevault.domain.taxonomy import categorize

MISSES_BEFORE_INACTIVE = 2
"""Consecutive successful runs without an item before it is considered gone (ADR-0004)."""

CHUNK_SIZE = 2000


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


class _Existing(NamedTuple):
    id: int
    price_minor: int
    price_regular_minor: int
    price_min30_minor: int | None
    is_active: bool


@dataclass(slots=True)
class _Counters:
    seen: int = 0
    new: int = 0
    price_drops: int = 0
    price_ups: int = 0
    returned: int = 0


def finalize_run(
    session: Session,
    run_id: int,
    *,
    deactivate: bool,
    now: datetime | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> RunStats:
    """Merge staging into products, sizes, categories and the price change log.

    `deactivate` is only true for successful runs: partial runs never count misses.
    """
    now = now or utcnow()
    run = session.get_one(ScrapeRun, run_id)
    site_id = run.site_id
    tree = (
        [CategoryNode.model_validate(n) for n in json.loads(run.category_tree_json)]
        if run.category_tree_json
        else None
    )

    categories = _CategoryIndex(session, site_id, tree, _staged_roots(session, run_id))
    brands = _BrandIndex(session, site_id)
    existing = {
        row.external_id: _Existing(
            row.id, row.price_minor, row.price_regular_minor, row.price_min30_minor, row.is_active
        )
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

    counters = _Counters()
    last = ""
    while True:
        rows = session.execute(
            select(RunItem.external_id, RunItem.gender_mask, RunItem.record_json)
            .where(RunItem.run_id == run_id, RunItem.external_id > last)
            .order_by(RunItem.external_id)
            .limit(chunk_size)
        ).all()
        if not rows:
            break
        last = rows[-1][0]
        chunk = [(ext, ProductRecord.model_validate_json(js), mask) for ext, mask, js in rows]
        _merge_chunk(session, site_id, run_id, now, chunk, existing, brands, categories, counters)

    recompute_depths(session, site_id)
    missing = removed = 0
    if deactivate:
        missing, removed = _count_misses(session, site_id, run_id)

    session.execute(delete(RunItem).where(RunItem.run_id == run_id))
    session.execute(delete(RunPage).where(RunPage.run_id == run_id))
    run.category_tree_json = None  # merged into `categories`; up to 150 KB per run otherwise
    return RunStats(
        seen=counters.seen,
        new=counters.new,
        price_drops=counters.price_drops,
        price_ups=counters.price_ups,
        returned=counters.returned,
        missing=missing,
        removed=removed,
    )


def _merge_chunk(
    session: Session,
    site_id: int,
    run_id: int,
    now: datetime,
    chunk: Sequence[tuple[str, ProductRecord, int]],
    existing: Mapping[str, _Existing],
    brands: _BrandIndex,
    categories: _CategoryIndex,
    counters: _Counters,
) -> None:
    brand_ids = brands.ensure(record.brand for _ext, record, _mask in chunk)
    categories.ensure(record.categories for _ext, record, _mask in chunk)
    parents = categories.parents
    names = categories.names

    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    changed: list[str] = []
    for external_id, record, mask in chunk:
        counters.seen += 1
        values = _product_values(record, mask, brand_ids[record.brand.external_id])
        path = path_names((c.external_id for c in record.categories), parents, names)
        values["category_slug"] = categorize(
            path, (record.name, record.subtitle), record.brand.name
        )
        values |= {
            "last_seen_at": now,
            "last_seen_run_id": run_id,
            "is_active": True,
            "missed_runs": 0,
        }
        old = existing.get(external_id)
        if old is None:
            counters.new += 1
            changed.append(external_id)
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
            counters.returned += 1
        if record.price_minor != old.price_minor:
            values["prev_price_minor"] = old.price_minor
            values["last_price_change_run_id"] = run_id
            if record.price_minor < old.price_minor:
                counters.price_drops += 1
            else:
                counters.price_ups += 1
        if (record.price_minor, record.price_regular_minor, record.price_min30_minor) != (
            old.price_minor,
            old.price_regular_minor,
            old.price_min30_minor,
        ):
            changed.append(external_id)
        updates.append(values | {"id": old.id})

    if inserts:
        session.execute(insert(Product), inserts)
    if updates:
        session.execute(update(Product), updates)

    product_ids = {ext: existing[ext].id for ext, _r, _m in chunk if ext in existing}
    if inserts:
        new_ids = session.execute(
            select(Product.external_id, Product.id).where(
                Product.site_id == site_id,
                Product.external_id.in_([row["external_id"] for row in inserts]),
            )
        )
        product_ids.update({ext: pid for ext, pid in new_ids})  # noqa: C416 (Result has .keys())

    records = {ext: record for ext, record, _mask in chunk}
    history = [
        {
            "product_id": product_ids[ext],
            "run_id": run_id,
            "observed_at": now,
            "price_minor": records[ext].price_minor,
            "price_regular_minor": records[ext].price_regular_minor,
            "price_min30_minor": records[ext].price_min30_minor,
            "discount_pct": records[ext].discount_pct,
        }
        for ext in changed
    ]
    if history:
        session.execute(insert(PriceHistory), history)

    _replace_children(session, chunk, product_ids, categories)


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


def _id_map(
    session: Session,
    model: type[Brand] | type[Category] | type[Product],
    site_id: int,
    external_ids: Iterable[str] | None = None,
) -> dict[str, int]:
    """external_id -> id for one site (optionally only for some external ids)."""
    stmt = select(model.external_id, model.id).where(model.site_id == site_id)
    if external_ids is not None:
        stmt = stmt.where(model.external_id.in_(list(external_ids)))
    # Not dict(rows): Result has .keys(), so dict() would treat it as a mapping.
    return {external_id: row_id for external_id, row_id in session.execute(stmt)}  # noqa: C416


@dataclass(slots=True)
class _BrandIndex:
    session: Session
    site_id: int
    ids: dict[str, int] = field(default_factory=dict)

    def ensure(self, refs: Iterable[BrandRef]) -> dict[str, int]:
        """Upsert the chunk's brands (names may change) and return external_id -> id."""
        brands = {b.external_id: b for b in refs}
        if brands:
            stmt = sqlite_insert(Brand).values(
                [
                    {
                        "site_id": self.site_id,
                        "external_id": b.external_id,
                        "name": b.name,
                        "name_key": brand_key(b.name),
                        "slug": b.slug,
                    }
                    for b in brands.values()
                ]
            )
            self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Brand.site_id, Brand.external_id],
                    set_={
                        "name": stmt.excluded.name,
                        "name_key": stmt.excluded.name_key,
                        "slug": stmt.excluded.slug,
                    },
                )
            )
            missing = [ext for ext in brands if ext not in self.ids]
            if missing:
                self.ids.update(_id_map(self.session, Brand, self.site_id, missing))
        return self.ids


class _CategoryIndex:
    """Category tree of a site during finalization.

    The shop's tree is the source of truth. Categories missing from it get a parent from the
    item lists, which are root-to-leaf paths glued together: a root starts a new path.
    """

    def __init__(
        self,
        session: Session,
        site_id: int,
        tree: Sequence[CategoryNode] | None,
        staged_roots: Iterable[str],
    ) -> None:
        self._session = session
        self._site_id = site_id
        self.nodes: dict[str, tuple[str, str | None, int]] = {
            n.external_id: (n.name, n.parent_external_id, n.depth) for n in tree or ()
        }
        self._roots = {ext for ext, (_n, parent, _d) in self.nodes.items() if parent is None}
        self._roots |= set(staged_roots)
        self.ids: dict[str, int] = {}
        self._store(list(self.nodes))

    @property
    def parents(self) -> dict[str, str | None]:
        return {ext: parent for ext, (_n, parent, _d) in self.nodes.items()}

    @property
    def names(self) -> dict[str, str]:
        return {ext: name for ext, (name, _p, _d) in self.nodes.items()}

    def ensure(self, category_lists: Iterable[Sequence[CategoryRef]]) -> None:
        added: list[str] = []
        for categories in category_lists:
            parent: str | None = None
            for category in categories:
                if category.external_id in self._roots:
                    parent = None
                if category.external_id not in self.nodes:
                    depth = self.nodes[parent][2] + 1 if parent is not None else 0
                    self.nodes[category.external_id] = (category.name, parent, depth)
                    added.append(category.external_id)
                parent = category.external_id
        self._store(added)

    def _store(self, external_ids: list[str]) -> None:
        if not external_ids:
            return
        stmt = sqlite_insert(Category).values(
            [
                {
                    "site_id": self._site_id,
                    "external_id": ext,
                    "name": self.nodes[ext][0],
                    "depth": self.nodes[ext][2],
                }
                for ext in external_ids
            ]
        )
        self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Category.site_id, Category.external_id],
                set_={"name": stmt.excluded.name, "depth": stmt.excluded.depth},
            )
        )
        wanted = set(external_ids) | {
            p for ext in external_ids if (p := self.nodes[ext][1]) is not None
        }
        self.ids.update(_id_map(self._session, Category, self._site_id, wanted - set(self.ids)))
        parents = [
            {"id": self.ids[ext], "parent_id": self.ids.get(parent) if parent else None}
            for ext in external_ids
            for parent in [self.nodes[ext][1]]
        ]
        self._session.execute(update(Category), parents)


def _staged_roots(session: Session, run_id: int) -> set[str]:
    """First category of every staged item: always a root of the shop's tree."""
    first = func.json_extract(RunItem.record_json, "$.categories[0].external_id")
    rows = session.scalars(select(first).where(RunItem.run_id == run_id).distinct())
    return {str(r) for r in rows if r is not None}


def with_ancestors(external_ids: Iterable[str], parents: Mapping[str, str | None]) -> set[str]:
    """The given categories plus all their ancestors, so a filter on a branch finds items
    whose list only names a deeper category."""
    out: set[str] = set()
    for external_id in external_ids:
        current: str | None = external_id
        while current is not None and current not in out:
            out.add(current)
            current = parents.get(current)
    return out


def _replace_children(
    session: Session,
    chunk: Sequence[tuple[str, ProductRecord, int]],
    product_ids: Mapping[str, int],
    categories: _CategoryIndex,
) -> None:
    ids = list(product_ids.values())
    session.execute(delete(ProductSize).where(ProductSize.product_id.in_(ids)))
    session.execute(delete(ProductCategory).where(ProductCategory.product_id.in_(ids)))

    parents = categories.parents
    sizes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for external_id, record, _mask in chunk:
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
        listed = (c.external_id for c in record.categories)
        for ext in with_ancestors(listed, parents):
            links.append({"product_id": product_id, "category_id": categories.ids[ext]})
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
