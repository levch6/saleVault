import asyncio
import random

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from salevault.db.engine import session_scope
from salevault.db.models import Product, RunItem
from salevault.db.runs import RunRepository
from salevault.scraper.base import Segment
from salevault.scraper.errors import ContractError
from salevault.scraper.runner import RunOptions
from salevault.scraper.service import RunOutcome, execute_run
from tests.fakes import FAKE_SITE, FakeAdapter, make_catalog, opener


async def no_sleep(_seconds: float) -> None:
    return None


async def run(
    adapter: FakeAdapter,
    factory: sessionmaker[Session],
    *,
    resume: bool = False,
    options: RunOptions | None = None,
) -> RunOutcome:
    return await execute_run(
        opener(adapter),
        FAKE_SITE,
        factory,
        options=options,
        resume=resume,
        sleep=no_sleep,
        rng=random.Random(1),
    )


def active_products(factory: sessionmaker[Session]) -> set[str]:
    with session_scope(factory) as session:
        return set(session.scalars(select(Product.external_id).where(Product.is_active.is_(True))))


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter(make_catalog({"M": 70, "D": 30}, unisex=5))


async def test_successful_run_fills_the_catalog(
    adapter: FakeAdapter, factory: sessionmaker[Session]
) -> None:
    outcome = await run(adapter, factory)

    assert outcome.status == "success"
    assert outcome.stats.new == len(adapter.items)
    assert active_products(factory) == {i.id for i in adapter.items}
    row = RunRepository(factory).get(outcome.run_id)
    assert row.status == "success"
    assert row.stats is not None
    assert row.stats["coverage"] == 1.0
    assert row.pages_done == row.pages_total


async def test_failed_run_can_be_resumed_without_refetching(
    adapter: FakeAdapter, factory: sessionmaker[Session]
) -> None:
    adapter.fail(Segment(sex="D"), 2, ContractError("HTTP 422"))
    with pytest.raises(ContractError):
        await run(adapter, factory)

    repo = RunRepository(factory)
    failed = repo.list_runs(limit=1)[0]
    assert failed.status == "failed"
    assert failed.error == "HTTP 422"
    with session_scope(factory) as session:
        assert (session.scalar(select(func.count()).select_from(RunItem)) or 0) > 0
    fetched_before = set(adapter.calls)
    adapter.calls.clear()

    outcome = await run(adapter, factory, resume=True)

    assert outcome.run_id == failed.id
    assert outcome.status == "success"
    assert not set(adapter.calls) & fetched_before - {("sex=D", 2)}, "done pages are skipped"
    assert ("sex=D", 2) in adapter.calls
    assert active_products(factory) == {i.id for i in adapter.items}


async def test_limited_run_is_partial_and_deactivates_nothing(
    adapter: FakeAdapter, factory: sessionmaker[Session]
) -> None:
    await run(adapter, factory)

    outcome = await run(adapter, factory, options=RunOptions(max_pages_per_segment=1))

    assert outcome.status == "partial"
    assert outcome.stats.removed == outcome.stats.missing == 0
    assert active_products(factory) == {i.id for i in adapter.items}


async def test_cancelled_run_is_recorded(
    adapter: FakeAdapter, factory: sessionmaker[Session]
) -> None:
    adapter.hang_on = ("sex=D", 2)
    task = asyncio.create_task(run(adapter, factory))
    await adapter.hung.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    last = RunRepository(factory).list_runs(limit=1)[0]
    assert last.status == "cancelled"
    assert last.pages_done > 0, "pages fetched before the cancel stay staged for --resume"


async def test_items_leave_the_catalog_after_two_successful_misses(
    adapter: FakeAdapter, factory: sessionmaker[Session]
) -> None:
    await run(adapter, factory)
    sold = adapter.items.pop()

    second = await run(adapter, factory)
    third = await run(adapter, factory)

    assert (second.stats.missing, second.stats.removed) == (1, 0)
    assert third.stats.removed == 1
    assert sold.id not in active_products(factory)
