import json
import re
from pathlib import Path
from typing import Any

import pytest

from salevault.domain.models import Gender
from salevault.scraper.base import HttpResponse, Segment
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError
from salevault.scraper.sites.answear_platform import AnswearPlatformAdapter
from salevault.scraper.sites.registry import PRM
from tests.fakes import FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures" / "answear_platform"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def ok(payload: dict[str, Any]) -> HttpResponse:
    return HttpResponse(status=200, text=json.dumps(payload))


def make_adapter(
    *responses: HttpResponse, open_status: int = 200
) -> tuple[AnswearPlatformAdapter, FakeTransport]:
    transport = FakeTransport(responses=list(responses), open_status=open_status)
    return AnswearPlatformAdapter(PRM, transport), transport


async def test_fetch_page_sends_the_frontend_request() -> None:
    adapter, transport = make_adapter(ok(load("products_page")))

    await adapter.fetch_page(Segment(sex="D", price=(0, 5000)), 3)

    path, body, headers = transport.posts[0]
    assert path == "/ua/api/products"
    assert body == {
        "sort": "",  # popularity: fewest unstable ties across pages
        "filters": {"sex": ["D"], "price": {"min": 0, "max": 5000}},
        "productsPerPage": 80,
        "category": "",
        "page": 3,
        "urlParams": "",
        "categoryTreeRequired": False,
        "sale": 1,
    }
    assert headers["x-tamago-locale"] == "uk_UA"
    assert headers["x-tamago-api-version"] == "4.10"
    assert headers["content-type"] == "application/json"


def test_root_body_has_no_filters() -> None:
    adapter, _ = make_adapter()

    assert adapter.request_body(Segment(), 1)["filters"] == {}


def test_parse_page_reads_count_facets_and_items() -> None:
    adapter, _ = make_adapter()

    page = adapter.parse_page(ok(load("products_page")))

    assert page.count == 9119
    assert len(page.items) == 6
    assert page.invalid_items == 0
    assert [(f.code, f.label) for f in page.facets.sex] == [
        ("D", "Women"),
        ("M", "Men"),
        ("H", "Home"),
    ]
    assert page.facets.price_range == (279, 141899)  # women-only fixture: its own price range


def test_normalize_maps_all_fields() -> None:
    adapter, _ = make_adapter()
    page = adapter.parse_page(ok(load("products_page")))

    item = next(p for p in page.items if p.external_id == "5906")

    assert item.site == "prm"
    assert item.url == "https://prm.com/ua/p/product-2-5906"
    assert item.brand.name == "Brand 2"
    assert item.price_minor == 29900
    assert item.price_regular_minor == 63900
    assert item.price_min30_minor == 36900
    assert item.discount_pct == 53
    assert item.discount_min30_pct == 18  # 18.97% truncated, like the site does
    assert item.savings_minor == 34000
    assert item.image is not None
    assert item.image.name == "TEST-0002_F1.avif"
    assert item.categories
    assert all(c.name.startswith("Category ") for c in item.categories)
    assert {s.availability: s.in_stock for s in item.sizes} == {
        "IN_STOCK": True,
        "OUT_OF_STOCK": False,
    }
    assert item.search_text.startswith("brand 2 brand 2 product 2")


def test_discount_matches_the_site_badge() -> None:
    adapter, _ = make_adapter()
    payload = load("products_page")
    page = adapter.parse_page(ok(payload))
    by_id = {p.external_id: p for p in page.items}

    checked = 0
    for raw in payload["items"]:
        for badge in raw["badges"]:
            if badge["type"] == "percentage":
                match = re.fullmatch(r"-(\d+)%", badge["text"])
                assert match is not None
                assert by_id[str(raw["id"])].discount_pct == int(match.group(1))
                checked += 1
    assert checked >= 4


def test_in_stock_covers_last_items() -> None:
    adapter, _ = make_adapter()
    page = adapter.parse_page(ok(load("products_page")))

    last_sizes = [s for p in page.items for s in p.sizes if s.availability == "LAST"]

    assert last_sizes
    assert all(s.in_stock for s in last_sizes)


def test_invalid_items_are_skipped_and_counted() -> None:
    adapter, _ = make_adapter()
    payload = load("products_page")
    del payload["items"][0]["price"]

    page = adapter.parse_page(ok(payload))

    assert page.invalid_items == 1
    assert len(page.items) == 5


@pytest.mark.parametrize(
    ("status", "text", "error"),
    [
        (0, "TypeError: Failed to fetch", TransientError),
        (500, "oops", TransientError),
        (503, "busy", TransientError),
        (403, "<html>Site Maintenance</html>", BlockedError),
        (429, "slow down", BlockedError),
        (422, '{"type": "requestValidationFailed"}', ContractError),
        (404, "not found", ContractError),
        (200, "<!doctype html><title>Site Maintenance</title>", BlockedError),
        (200, '{"unexpected": true}', ContractError),
    ],
)
def test_status_and_body_errors(status: int, text: str, error: type[Exception]) -> None:
    adapter, _ = make_adapter()

    with pytest.raises(error):
        adapter.parse_page(HttpResponse(status=status, text=text))


def test_root_segments_follow_the_sex_facet() -> None:
    adapter, _ = make_adapter()
    root = adapter.parse_page(ok(load("products_root")))

    assert [s.key for s in adapter.root_segments(root)] == ["sex=D", "sex=M", "sex=H"]


def test_gender_mapping() -> None:
    adapter, _ = make_adapter()

    assert adapter.gender_of(Segment(sex="M")) == Gender.MEN
    assert adapter.gender_of(Segment(sex="D")) == Gender.WOMEN
    assert adapter.gender_of(Segment(sex="H")) == Gender.HOME
    assert adapter.gender_of(Segment(sex="X")) == Gender(0)
    assert adapter.gender_of(Segment()) == Gender(0)


async def test_warm_up_opens_the_sale_page() -> None:
    adapter, transport = make_adapter()

    await adapter.warm_up()

    assert transport.opened == ["https://prm.com/ua/sale/"]


@pytest.mark.parametrize(
    ("status", "error"), [(403, BlockedError), (500, ScrapeError), (0, ScrapeError)]
)
async def test_warm_up_failures(status: int, error: type[Exception]) -> None:
    adapter, _ = make_adapter(open_status=status)

    with pytest.raises(error):
        await adapter.warm_up()
