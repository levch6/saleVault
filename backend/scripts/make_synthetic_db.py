"""Build a large synthetic catalog through the real pipeline (staging + finalize), for benchmarks.

Usage:
    uv run python scripts/make_synthetic_db.py DATA_DIR [--items 200000] [--seed 1]

Creates DATA_DIR/salevault.db with two successful PRM-like runs: the second one changes ~5% of
prices, adds ~1% new items and misses ~1%, so New / Price drop / grace logic has data too.
"""

import argparse
import random
import time
from pathlib import Path

from salevault.db.engine import (
    analyze,
    create_db_engine,
    make_session_factory,
    session_scope,
    sqlite_url,
)
from salevault.db.finalize import finalize_run
from salevault.db.migrate import upgrade
from salevault.db.runs import DbRunSink, RunRepository
from salevault.domain.models import (
    BrandRef,
    CategoryNode,
    CategoryRef,
    Gender,
    ImageRef,
    ProductRecord,
    SizeRecord,
)
from salevault.scraper.base import Facets, PageResult, Segment
from salevault.scraper.sites.registry import PRM

LETTERS = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
SHOES = [str(n) for n in range(36, 47)] + [f"{n} 1/3" for n in range(36, 46)]
WORDS = ["jacket", "coat", "sneakers", "boots", "dress", "jeans", "shirt", "bag", "cap", "scarf"]
PAGE = 400


def build_tree(rng: random.Random) -> list[CategoryNode]:
    nodes: list[CategoryNode] = []
    next_id = 1
    for root_name in ("Men", "Women", "Lifestyle"):
        root = str(next_id)
        next_id += 1
        nodes.append(
            CategoryNode(external_id=root, name=root_name, parent_external_id=None, depth=0)
        )
        for a in range(10):
            l1 = str(next_id)
            next_id += 1
            nodes.append(
                CategoryNode(
                    external_id=l1, name=f"{root_name} {a}", parent_external_id=root, depth=1
                )
            )
            for b in range(6):
                l2 = str(next_id)
                next_id += 1
                nodes.append(
                    CategoryNode(
                        external_id=l2, name=f"Group {a}.{b}", parent_external_id=l1, depth=2
                    )
                )
                for c in range(rng.randint(2, 6)):
                    l3 = str(next_id)
                    next_id += 1
                    nodes.append(
                        CategoryNode(
                            external_id=l3, name=f"Kind {a}.{b}.{c}", parent_external_id=l2, depth=3
                        )
                    )
    return nodes


def path_to(leaf: CategoryNode, by_id: dict[str, CategoryNode]) -> list[CategoryRef]:
    path = []
    node: CategoryNode | None = leaf
    while node is not None:
        path.append(CategoryRef(external_id=node.external_id, name=node.name))
        node = by_id.get(node.parent_external_id) if node.parent_external_id else None
    return path[::-1]


def make_item(
    i: int,
    rng: random.Random,
    leaves: list[CategoryNode],
    by_id: dict[str, CategoryNode],
    price_factor: float = 1.0,
) -> tuple[ProductRecord, Gender]:
    item_rng = random.Random(i)  # stable per item across runs
    gender = item_rng.choices(
        [Gender.MEN, Gender.WOMEN, Gender.HOME, Gender.MEN | Gender.WOMEN], [45, 40, 5, 10]
    )[0]
    regular = round(item_rng.lognormvariate(8.0, 0.9) / 10) * 10 + 9
    discount = min(0.85, max(0.03, item_rng.betavariate(2.2, 4.0)))
    price = max(99, int(regular * (1 - discount) * price_factor))
    min30 = regular if item_rng.random() < 0.6 else int(regular * item_rng.uniform(0.6, 1.0))
    pool = SHOES if item_rng.random() < 0.3 else LETTERS
    labels = item_rng.sample(pool, k=min(len(pool), item_rng.randint(1, 8)))
    leaf = item_rng.choice(leaves)
    categories = path_to(leaf, by_id)
    if gender == Gender.MEN | Gender.WOMEN:
        categories += path_to(item_rng.choice(leaves), by_id)
    brand = item_rng.randint(1, 400)
    word = item_rng.choice(WORDS)
    record = ProductRecord.create(
        site=PRM.code,
        external_id=str(i),
        url=f"https://prm.com/ua/p/synthetic-{i}",
        name=f"Brand {brand} {word} {i}",
        subtitle=f"color {i % 17} model SYN-{i:06d}",
        brand=BrandRef(external_id=str(brand), name=f"Brand {brand}"),
        color=f"color {i % 17}",
        image=ImageRef(name=f"SYN-{i:06d}_F1.jpg", version="1"),
        gallery=tuple(ImageRef(name=f"SYN-{i:06d}_F{n}.jpg", version="1") for n in range(2, 5)),
        categories=tuple(categories),
        price_minor=price * 100,
        price_regular_minor=regular * 100,
        price_min30_minor=min30 * 100,
        available_for_buy=True,
        sizes=tuple(
            SizeRecord(
                external_id=label,
                label=label,
                variation_id=f"{i}-{label}",
                ean=None,
                availability=item_rng.choice(["IN_STOCK", "LAST", "OUT_OF_STOCK"]),
                in_stock=False,
            ).model_copy(update={"in_stock": item_rng.random() < 0.55})
            for label in labels
        ),
    )
    return record, gender


def run(factory, ids: list[int], tree, leaves, by_id, rng, changed: set[int]) -> None:  # type: ignore[no-untyped-def]
    repo = RunRepository(factory)
    run_id = repo.start(PRM.site_info, trigger="cli")
    sink = DbRunSink(factory, run_id)
    sink.on_category_tree(tree)
    t0 = time.perf_counter()
    for start in range(0, len(ids), PAGE):
        batch = [
            make_item(i, rng, leaves, by_id, 0.9 if i in changed else 1.0)
            for i in ids[start : start + PAGE]
        ]
        for gender in {g for _, g in batch}:
            records = tuple(r for r, g in batch if g == gender)
            sink.on_page(
                Segment(),
                start // PAGE + 1,
                gender,
                PageResult(count=len(ids), items=records, facets=Facets(), raw="{}"),
            )
    t1 = time.perf_counter()
    with session_scope(factory) as session:
        stats = finalize_run(session, run_id, deactivate=True)
    t2 = time.perf_counter()
    repo.finish(run_id, "success", stats=stats.to_json())
    print(f"run #{run_id}: staged {len(ids):,} items in {t1 - t0:.1f} s,", end=" ")
    print(f"finalized in {t2 - t1:.1f} s ({stats})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--items", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    db_path = args.data_dir / "salevault.db"
    if db_path.exists():
        raise SystemExit(f"{db_path} already exists")
    engine = create_db_engine(sqlite_url(db_path))
    upgrade(engine)
    factory = make_session_factory(engine)
    rng = random.Random(args.seed)
    tree = build_tree(rng)
    by_id = {n.external_id: n for n in tree}
    leaves = [n for n in tree if n.depth == 3]

    first = list(range(args.items))
    run(factory, first, tree, leaves, by_id, rng, changed=set())
    kept = [i for i in first if rng.random() > 0.01]
    second = kept + list(range(args.items, args.items + args.items // 100))
    changed = {i for i in kept if rng.random() < 0.05}
    run(factory, second, tree, leaves, by_id, rng, changed=changed)
    t = time.perf_counter()
    analyze(factory)
    print(
        f"ANALYZE in {time.perf_counter() - t:.1f} s; db size {db_path.stat().st_size / 1e6:.0f} MB"
    )


if __name__ == "__main__":
    main()
