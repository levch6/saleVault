"""Keep every product's place in the shared category tree up to date (`domain/taxonomy.py`).

A merge categorizes the products it touches. When the tree or its rules change
(`TAXONOMY_VERSION`), every stored product is categorized again on the next start, from what
the database holds: the shop's category path, the name, the subtitle and the brand.
"""

import json
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from salevault.db.engine import make_session_factory, session_scope
from salevault.db.models import Brand, Category, Product, ProductCategory, Setting, Site
from salevault.db.types import utcnow
from salevault.domain.taxonomy import OTHER, TAXONOMY_VERSION, categorize

log = logging.getLogger(__name__)

TAXONOMY_KEY = "taxonomy"
"""Settings row with the version of the rules the stored categories come from."""
CHUNK_SIZE = 5_000

_RECOMPUTE_DEPTHS = text(
    """
    WITH RECURSIVE tree(id, depth) AS (
        SELECT id, 0 FROM categories WHERE parent_id IS NULL AND site_id = :site_id
        UNION ALL
        SELECT c.id, tree.depth + 1 FROM categories AS c JOIN tree ON c.parent_id = tree.id
        WHERE tree.depth < 64
    )
    UPDATE categories SET depth = (SELECT depth FROM tree WHERE tree.id = categories.id)
    WHERE id IN (SELECT id FROM tree)
    """
)


def recompute_depths(session: Session, site_id: int) -> None:
    """Set every category's depth from its parent links (a parent can change after a category
    was first stored)."""
    session.execute(_RECOMPUTE_DEPTHS, {"site_id": site_id})


def path_names(
    listed: Iterable[str], parents: Mapping[str, str | None], names: Mapping[str, str]
) -> list[str]:
    """The evidence path of a product: the deepest listed category and its ancestors up to the
    root, then the categories of its other paths, deepest first."""
    chains: list[list[str]] = []
    for external_id in listed:
        chain: list[str] = []
        current: str | None = external_id
        while current is not None and current not in chain:
            chain.append(current)
            current = parents.get(current)
        chains.append(chain)
    if not chains:
        return []
    deepest = max(chains, key=len)  # the first of the longest, as listed
    rest = sorted(
        {node: len(chain) - i for chain in chains for i, node in enumerate(chain)}.items(),
        key=lambda item: -item[1],
    )
    ordered = [*deepest, *(node for node, _depth in rest if node not in deepest)]
    return [names[node] for node in ordered if node in names]


def recategorize(session: Session, site_id: int | None = None) -> int:
    """Categorize the stored products again; returns how many moved to another category."""
    moved = 0
    last = 0
    while True:
        query = (
            select(Product.id, Product.name, Product.subtitle, Product.category_slug, Brand.name)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Product.id > last)
            .order_by(Product.id)
            .limit(CHUNK_SIZE)
        )
        if site_id is not None:
            query = query.where(Product.site_id == site_id)
        rows = session.execute(query).all()
        if not rows:
            return moved
        last = rows[-1][0]
        linked: defaultdict[int, list[str]] = defaultdict(list)
        parents: dict[str, str | None] = {}
        names: dict[str, str] = {}
        for product_id, category_id, parent_id, name in session.execute(
            select(ProductCategory.product_id, Category.id, Category.parent_id, Category.name)
            .join(Category, Category.id == ProductCategory.category_id)
            .where(ProductCategory.product_id.in_([row[0] for row in rows]))
        ):
            key = str(category_id)
            linked[product_id].append(key)
            parents[key] = str(parent_id) if parent_id is not None else None
            names[key] = name
        changes = []
        for product_id, name, subtitle, current, brand in rows:
            path = path_names(linked.get(product_id, ()), parents, names)
            slug = categorize(path, (name, subtitle), brand)
            if slug != current:
                changes.append({"id": product_id, "category_slug": slug})
        if changes:
            session.execute(update(Product), changes)
            moved += len(changes)


def ensure_categorized(engine: Engine) -> None:
    """Categorize every product again if the stored categories come from older rules."""
    factory = make_session_factory(engine, write=True)
    with session_scope(factory) as session:
        stored = session.scalar(select(Setting.value_json).where(Setting.key == TAXONOMY_KEY))
        if stored is not None and json.loads(stored).get("version") == TAXONOMY_VERSION:
            return
        moved = recategorize(session)
        mark_categorized(session)
    if stored is not None or moved:
        log.info(
            "Categorized the catalog with rules v%d: %d products moved", TAXONOMY_VERSION, moved
        )


def mark_categorized(session: Session) -> None:
    """Record the rules version and the time, so cached facets of a running server expire."""
    value = json.dumps({"version": TAXONOMY_VERSION, "updated_at": utcnow().isoformat()})
    stmt = sqlite_insert(Setting).values(key=TAXONOMY_KEY, value_json=value)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Setting.key], set_={"value_json": stmt.excluded.value_json}
        )
    )


@dataclass(frozen=True, slots=True)
class Coverage:
    site: str
    total: int
    specific: int
    """In a leaf that names a kind of product."""
    catch_all: int
    """In a group's "Other ..." leaf."""
    other: int
    """In the top-level "Other"."""


def coverage(session: Session) -> list[Coverage]:
    """How well the active products of every shop are categorized."""
    counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for code, slug, n in session.execute(
        select(Site.code, Product.category_slug, func.count())
        .join(Site, Site.id == Product.site_id)
        .where(Product.is_active.is_(True))
        .group_by(Site.code, Product.category_slug)
    ):
        counts[code][slug] += n
    out = []
    for code in sorted(counts):
        by_slug = counts[code]
        other = by_slug[OTHER]
        catch_all = sum(n for slug, n in by_slug.items() if slug.endswith(".other"))
        total = sum(by_slug.values())
        out.append(Coverage(code, total, total - other - catch_all, catch_all, other))
    return out
