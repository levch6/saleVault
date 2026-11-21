import random

import pytest

from salevault.domain.models import Gender
from salevault.scraper.base import Segment
from salevault.scraper.errors import (
    BlockedError,
    BudgetExceededError,
    ContractError,
    TransientError,
)
from salevault.scraper.runner import RunOptions, ScrapeRunner
from tests.fakes import FakeAdapter, make_catalog


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_runner(
    adapter: FakeAdapter, **options: object
) -> tuple[ScrapeRunner, SleepRecorder, list[tuple[str, int]]]:
    sleep = SleepRecorder()
    raw: list[tuple[str, int]] = []
    runner = ScrapeRunner(
        adapter,
        RunOptions(**options),  # type: ignore[arg-type]
        sleep=sleep,
        rng=random.Random(42),
        raw_sink=lambda segment, page, _text: raw.append((segment.key, page)),
    )
    return runner, sleep, raw


@pytest.fixture
def adapter() -> FakeAdapter:
    # API cap in the fake: 10 per page x 5 pages = 50, safe limit 48.
    return FakeAdapter(make_catalog({"M": 120, "D": 40, "H": 7}, unisex=15))


async def test_full_run_collects_every_item_once(adapter: FakeAdapter) -> None:
    runner, sleep, raw = make_runner(adapter)

    result = await runner.run()

    assert adapter.warmed
    assert result.complete
    assert result.expected_total == len(adapter.items)
    assert set(result.genders) == {i.id for i in adapter.items}
    assert len(adapter.calls) == len(set(adapter.calls)), "no page is fetched twice"
    assert result.requests == len(adapter.calls)
    assert raw == adapter.calls
    assert all(s.ratio == 1.0 and s.expected <= runner.safe_limit for s in result.segments)
    assert len(sleep.calls) == result.requests
    assert all(0.8 <= s <= 1.6 for s in sleep.calls)


async def test_unisex_items_get_both_gender_bits(adapter: FakeAdapter) -> None:
    runner, _, _ = make_runner(adapter)

    result = await runner.run()

    for item in adapter.items:
        expected = Gender(0)
        for sex in item.sex:
            expected |= {"M": Gender.MEN, "D": Gender.WOMEN, "H": Gender.HOME}[sex]
        assert result.genders[item.id] == expected


async def test_transient_errors_are_retried_with_backoff(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="D"), 1, TransientError("502"), TransientError("timeout"))
    runner, sleep, _ = make_runner(adapter)

    result = await runner.run()

    assert result.complete
    assert result.retries == 2
    backoffs = [s for s in sleep.calls if s >= 2]
    assert 2 <= backoffs[0] <= 3
    assert 4 <= backoffs[1] <= 5


async def test_transient_errors_give_up_after_max_retries(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="D"), 1, *[TransientError("502")] * 3)
    runner, _, _ = make_runner(adapter, max_retries=2)

    with pytest.raises(TransientError):
        await runner.run()


async def test_block_is_waited_out_once(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="H"), 1, BlockedError("HTTP 403"))
    runner, sleep, _ = make_runner(adapter, block_pause_s=60.0)

    result = await runner.run()

    assert result.complete
    assert sleep.calls.count(60.0) == 1


async def test_refusals_are_counted_per_run_not_per_page(adapter: FakeAdapter) -> None:
    """A shop that refuses every now and then is not waited out again and again."""
    adapter.fail(Segment(sex="M"), 1, BlockedError("HTTP 429"))
    adapter.fail(Segment(sex="D"), 1, BlockedError("HTTP 429"))
    runner, sleep, _ = make_runner(adapter, block_pause_s=60.0)

    with pytest.raises(BlockedError):
        await runner.run()

    assert sleep.calls.count(60.0) == 1


async def test_the_response_that_breaks_the_contract_is_archived(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="D"), 1, ContractError("unexpected shape", raw='{"odd": true}'))
    runner, _, raw = make_runner(adapter)

    with pytest.raises(ContractError):
        await runner.run()

    assert ("sex=D", 1) in raw


async def test_repeated_block_stops_the_run(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="H"), 1, BlockedError("HTTP 403"), BlockedError("HTTP 403"))
    runner, _, _ = make_runner(adapter)

    with pytest.raises(BlockedError):
        await runner.run()


async def test_contract_errors_are_not_retried(adapter: FakeAdapter) -> None:
    adapter.fail(Segment(sex="H"), 1, ContractError("HTTP 422"))
    runner, _, _ = make_runner(adapter)

    with pytest.raises(ContractError):
        await runner.run()
    assert adapter.calls.count(("sex=H", 1)) == 1


async def test_request_budget_is_enforced(adapter: FakeAdapter) -> None:
    runner, _, _ = make_runner(adapter, max_requests=3)

    with pytest.raises(BudgetExceededError):
        await runner.run()
    assert len(adapter.calls) == 3


async def test_max_pages_limits_the_run_and_marks_it_incomplete(adapter: FakeAdapter) -> None:
    runner, _, _ = make_runner(adapter, max_pages_per_segment=1)

    result = await runner.run()

    assert result.limited
    assert not result.complete
    assert all(page == 1 for _, page in adapter.calls)


async def test_missing_items_make_the_run_partial() -> None:
    adapter = FakeAdapter(make_catalog({"M": 30, "D": 30}))  # small enough not to be split
    adapter.blank_pages.add(("sex=D", 2))
    runner, _, _ = make_runner(adapter)

    result = await runner.run()

    assert not result.complete
    d = next(s for s in result.segments if s.key == "sex=D")
    assert d.fetched < d.expected


async def test_concurrent_workers_collect_the_same_items(adapter: FakeAdapter) -> None:
    runner, _, _ = make_runner(adapter, concurrency=3)

    result = await runner.run()

    assert result.complete
    assert set(result.genders) == {i.id for i in adapter.items}


async def test_light_mode_keeps_summaries_but_not_items(adapter: FakeAdapter) -> None:
    full, _, _ = make_runner(adapter)
    full_result = await full.run()
    adapter.calls.clear()
    light, _, _ = make_runner(adapter, keep_items=False)

    result = await light.run()

    assert result.items is None
    assert result.item_count == len(adapter.items)
    assert result.complete
    assert sum(result.discount_counts.values()) == result.item_count
    assert result.discount_counts == full_result.discount_counts
    assert [p.external_id for p in result.top] == [p.external_id for p in full_result.top]
    assert len(result.top) == min(50, len(adapter.items))
