"""Seed a test DB through the real pipeline: stage pages, finalize, finish the run."""

from collections.abc import Sequence

from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import session_scope
from salevault.db.finalize import finalize_run
from salevault.db.runs import DbRunSink, RunRepository
from salevault.domain.models import CategoryNode, CategoryRef, Gender, ProductRecord, SizeRecord
from salevault.scraper.base import Facets, PageResult, Segment, SiteInfo
from tests.fakes import FakeItem, make_record


def seed_run(
    factory: sessionmaker[Session],
    site: SiteInfo,
    pages: Sequence[tuple[Gender, Sequence[ProductRecord]]],
    *,
    status: str = "success",
    tree: Sequence[CategoryNode] | None = None,
) -> int:
    run_id = RunRepository(factory).start(site, trigger="cli")
    complete_run(factory, run_id, pages, status=status, tree=tree)
    return run_id


def complete_run(
    factory: sessionmaker[Session],
    run_id: int,
    pages: Sequence[tuple[Gender, Sequence[ProductRecord]]],
    *,
    status: str = "success",
    tree: Sequence[CategoryNode] | None = None,
) -> None:
    """Stage the pages of an already started run, merge it and finish it."""
    sink = DbRunSink(factory, run_id)
    if tree:
        sink.on_category_tree(tree)
    for page_no, (gender, records) in enumerate(pages, start=1):
        result = PageResult(count=len(records), items=tuple(records), facets=Facets(), raw="{}")
        sink.on_page(Segment(), page_no, gender, result)
    with session_scope(factory) as session:
        stats = finalize_run(session, run_id, deactivate=status == "success")
    RunRepository(factory).finish(run_id, status, stats=stats.to_json())


def product(
    item_id: str,
    price: int,
    *,
    regular: int,
    min30: int | None = None,
    brand: str = "1",
    sizes: Sequence[tuple[str, bool]] = (("S", True),),
    categories: Sequence[tuple[str, str]] | None = None,
) -> ProductRecord:
    record = make_record(
        FakeItem(item_id, frozenset(), price), regular=regular, min30=min30, brand=brand
    )
    if categories is not None:
        record = record.model_copy(
            update={"categories": tuple(CategoryRef(external_id=e, name=n) for e, n in categories)}
        )
    return record.model_copy(
        update={
            "sizes": tuple(
                SizeRecord(
                    external_id=label,
                    label=label,
                    variation_id=f"{item_id}-{label}",
                    ean=None,
                    availability="IN_STOCK" if in_stock else "OUT_OF_STOCK",
                    in_stock=in_stock,
                )
                for label, in_stock in sizes
            )
        }
    )
