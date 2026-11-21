from datetime import UTC, datetime

from rich.console import Console

from salevault.domain.models import Gender
from salevault.scraper.report import format_uah, gender_label, render_summary, top_discounts
from salevault.scraper.runner import ScrapeResult, SegmentReport
from tests.fakes import FakeItem, make_record


def test_format_uah_groups_thousands() -> None:
    assert format_uah(1789900) == "17 899 UAH"
    assert format_uah(26900) == "269 UAH"


def test_gender_label() -> None:
    assert gender_label(Gender.MEN) == "M"
    assert gender_label(Gender.MEN | Gender.WOMEN) == "M+W"
    assert gender_label(Gender(0)) == "-"


def test_top_discounts_orders_by_discount_then_savings() -> None:
    cheap = make_record(FakeItem("a", frozenset({"M"}), 100))  # 50% off, saves 100
    pricey = make_record(FakeItem("b", frozenset({"M"}), 1000))  # 50% off, saves 1000

    top = top_discounts({"a": cheap, "b": pricey}, 1)

    assert [p.external_id for p in top] == ["b"]


def test_render_summary_smoke() -> None:
    record = make_record(FakeItem("a", frozenset({"M"}), 100))
    result = ScrapeResult(
        site="fake",
        started_at=datetime(2026, 11, 21, 10, 0, tzinfo=UTC),
        finished_at=datetime(2026, 11, 21, 10, 5, tzinfo=UTC),
        expected_total=1,
        items={"a": record},
        genders={"a": Gender.MEN},
        segments=[SegmentReport(key="sex=M", expected=1, fetched=1, pages=1, truncated=False)],
        requests=2,
        retries=0,
        invalid_items=0,
        limited=False,
        segment_threshold=0.98,
        total_threshold=0.99,
    )
    console = Console(record=True, width=120)

    render_summary(console, result, top=5)

    text = console.export_text()
    assert "COMPLETE" in text
    assert "1 unique of 1 expected (100.0%)" in text
    assert "-50%" in text
