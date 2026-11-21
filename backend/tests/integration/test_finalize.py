from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import session_scope
from salevault.db.finalize import RunStats, finalize_run
from salevault.db.models import (
    Brand,
    Category,
    PriceHistory,
    Product,
    ProductCategory,
    ProductSize,
    RunItem,
    RunPage,
)
from salevault.db.runs import DbRunSink, RunRepository
from salevault.domain.models import Gender, ProductRecord
from salevault.scraper.base import Facets, PageResult, Segment
from tests.fakes import FAKE_SITE, FakeItem, make_record


def item(item_id: str, price: int, *, regular: int | None = None) -> ProductRecord:
    return make_record(FakeItem(item_id, frozenset({"M"}), price), regular=regular)


def run_once(
    factory: sessionmaker[Session],
    pages: Sequence[tuple[Gender, Sequence[ProductRecord]]],
    *,
    status: str = "success",
) -> tuple[int, RunStats]:
    repo = RunRepository(factory)
    run_id = repo.start(FAKE_SITE, trigger="cli")
    sink = DbRunSink(factory, run_id)
    for page_no, (gender, records) in enumerate(pages, start=1):
        result = PageResult(count=len(records), items=tuple(records), facets=Facets(), raw="{}")
        sink.on_page(Segment(sex="M"), page_no, gender, result)
    with session_scope(factory) as session:
        stats = finalize_run(session, run_id, deactivate=status == "success")
    repo.finish(run_id, status, stats=stats.to_json())
    return run_id, stats


def products(factory: sessionmaker[Session]) -> dict[str, Product]:
    with session_scope(factory) as session:
        return {p.external_id: p for p in session.scalars(select(Product))}


def count(factory: sessionmaker[Session], model: type) -> int:
    with session_scope(factory) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_first_run_creates_the_catalog(factory: sessionmaker[Session]) -> None:
    run_id, stats = run_once(factory, [(Gender.MEN, [item("a", 100), item("b", 200)])])

    assert stats == RunStats(
        seen=2, new=2, price_drops=0, price_ups=0, returned=0, missing=0, removed=0
    )
    rows = products(factory)
    assert set(rows) == {"a", "b"}
    a = rows["a"]
    assert (a.price_minor, a.price_regular_minor, a.discount_pct) == (10000, 20000, 50)
    assert a.is_active
    assert a.first_seen_run_id == a.last_seen_run_id == run_id
    assert a.gender_mask == Gender.MEN
    assert a.prev_price_minor is None
    assert count(factory, PriceHistory) == 2
    assert count(factory, Brand) == 1
    assert count(factory, ProductSize) == 4
    assert count(factory, ProductCategory) == 4
    assert count(factory, RunItem) == count(factory, RunPage) == 0, "staging is cleared"


def test_category_tree_keeps_parents(factory: sessionmaker[Session]) -> None:
    run_once(factory, [(Gender.MEN, [item("a", 100)])])

    with session_scope(factory) as session:
        by_ext = {c.external_id: c for c in session.scalars(select(Category))}
    assert by_ext["100"].parent_id is None
    assert by_ext["101"].parent_id == by_ext["100"].id
    assert (by_ext["100"].depth, by_ext["101"].depth) == (0, 1)


def test_price_changes_are_logged_and_flagged(factory: sessionmaker[Session]) -> None:
    run_once(
        factory,
        [(Gender.MEN, [item("drop", 100), item("up", 100), item("same", 100), item("reg", 100)])],
    )

    run2, stats = run_once(
        factory,
        [
            (
                Gender.MEN,
                [
                    item("drop", 80),
                    item("up", 120),
                    item("same", 100),
                    item("reg", 100, regular=300),  # only the reference price moved
                    item("new", 50),
                ],
            )
        ],
    )

    assert (stats.new, stats.price_drops, stats.price_ups) == (1, 1, 1)
    rows = products(factory)
    assert rows["drop"].prev_price_minor == 10000
    assert rows["drop"].last_price_change_run_id == run2
    assert rows["up"].prev_price_minor == 10000
    assert rows["same"].prev_price_minor is None
    assert rows["reg"].prev_price_minor is None, "a reference-only change is not a price change"
    assert rows["reg"].price_regular_minor == 30000
    # history: 4 first sightings + drop, up, reg, new
    assert count(factory, PriceHistory) == 8


def test_deactivation_waits_for_two_misses_and_items_can_return(
    factory: sessionmaker[Session],
) -> None:
    run_once(factory, [(Gender.MEN, [item("stay", 100), item("gone", 100)])])

    _, second = run_once(factory, [(Gender.MEN, [item("stay", 100)])])
    assert (second.missing, second.removed) == (1, 0)
    assert products(factory)["gone"].is_active
    assert products(factory)["gone"].missed_runs == 1

    _, third = run_once(factory, [(Gender.MEN, [item("stay", 100)])])
    assert (third.missing, third.removed) == (0, 1)
    assert not products(factory)["gone"].is_active

    _, fourth = run_once(factory, [(Gender.MEN, [item("stay", 100), item("gone", 90)])])
    assert fourth.returned == 1
    gone = products(factory)["gone"]
    assert gone.is_active
    assert gone.missed_runs == 0
    assert gone.prev_price_minor == 10000


def test_partial_runs_never_count_misses(factory: sessionmaker[Session]) -> None:
    run_once(factory, [(Gender.MEN, [item("a", 100), item("b", 100)])])

    _, stats = run_once(factory, [(Gender.MEN, [item("a", 100)])], status="partial")
    _, again = run_once(factory, [(Gender.MEN, [item("a", 100)])], status="partial")

    assert (stats.missing, stats.removed, again.removed) == (0, 0, 0)
    b = products(factory)["b"]
    assert b.is_active
    assert b.missed_runs == 0


def test_unisex_items_merge_gender_bits(factory: sessionmaker[Session]) -> None:
    shared = item("u", 100)

    run_once(factory, [(Gender.MEN, [shared]), (Gender.WOMEN, [shared, item("w", 100)])])

    rows = products(factory)
    assert rows["u"].gender_mask == Gender.MEN | Gender.WOMEN
    assert rows["w"].gender_mask == Gender.WOMEN
