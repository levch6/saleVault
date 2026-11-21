import itertools

from salevault.scraper.base import PageResult, Segment
from salevault.scraper.segmentation import plan_segments
from tests.fakes import FakeAdapter, FakeItem, make_catalog


async def test_small_segments_are_not_split() -> None:
    adapter = FakeAdapter(make_catalog({"M": 20, "D": 30}))

    planned = await plan_segments(
        adapter.fetch_page,
        [Segment(sex="M"), Segment(sex="D")],
        limit=48,
        fallback_price_range=None,
    )

    assert [(p.segment.key, p.count) for p in planned] == [("sex=M", 20), ("sex=D", 30)]
    assert adapter.calls == [("sex=M", 1), ("sex=D", 1)]


async def test_large_segment_is_bisected_by_price_without_overlap() -> None:
    items = make_catalog({"M": 200})
    adapter = FakeAdapter(items)

    planned = await plan_segments(
        adapter.fetch_page, [Segment(sex="M")], limit=48, fallback_price_range=None
    )

    assert all(p.count <= 48 and not p.truncated for p in planned)
    assert sum(p.count for p in planned) == 200
    bounds = sorted(p.segment.price for p in planned if p.segment.price)
    for (_, high), (low, _) in itertools.pairwise(bounds):
        assert low == high + 1  # contiguous integer ranges, no gaps or overlaps
    assert bounds[0][0] == min(i.price for i in items)
    assert bounds[-1][1] == max(i.price for i in items)


async def test_unsplittable_segment_is_marked_truncated() -> None:
    items = [FakeItem(f"x{i}", frozenset({"M"}), 500) for i in range(60)]
    adapter = FakeAdapter(items)

    planned = await plan_segments(
        adapter.fetch_page, [Segment(sex="M")], limit=48, fallback_price_range=None
    )

    assert len(planned) == 1
    assert planned[0].truncated
    assert planned[0].count == 60


async def test_known_first_page_is_reused() -> None:
    adapter = FakeAdapter(make_catalog({"M": 5}))
    root: PageResult = await adapter.fetch_page(Segment(), 1)
    adapter.calls.clear()

    planned = await plan_segments(
        adapter.fetch_page,
        [Segment()],
        limit=48,
        fallback_price_range=None,
        known_first_pages={Segment(): root},
    )

    assert adapter.calls == []
    assert planned[0].first_page is root


def test_segment_keys_are_stable() -> None:
    assert Segment().key == "all"
    assert Segment(sex="M").key == "sex=M"
    assert Segment(sex="M", price=(0, 5000)).key == "sex=M;price=0-5000"
    assert Segment(sex="D").with_price(1, 2) == Segment(sex="D", price=(1, 2))
