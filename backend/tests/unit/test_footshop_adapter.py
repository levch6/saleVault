import json
from pathlib import Path
from typing import Any

import pytest

from salevault.domain.models import Gender
from salevault.scraper.base import HttpResponse, Segment
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError
from salevault.scraper.sites.footshop import FootshopAdapter, extract_listing
from salevault.scraper.sites.registry import FOOTSHOP_UA, create_adapter, image_urls
from tests.fakes import FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures" / "footshop"
SALE = "https://www.footshop.ua/uk/872-znizhki"
MEN = "https://www.footshop.ua/uk/2536-colovica-moda-znizki"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def page_html(listing: dict[str, Any]) -> str:
    """A catalog page as the shop serves it: the listing JSON in an HTML comment, with `&` and
    `>` escaped (Hypernova's encoding), among other scripts."""
    encoded = json.dumps(listing, ensure_ascii=False).replace("&", "&amp;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html><html><head><title>Sale</title></head><body>"
        '<script type="application/json" data-hypernova-key="Root" data-hypernova-id="a">'
        '<!--{"data":{}}--></script>'
        '<script type="application/json" data-hypernova-key="ProductListing" '
        f'data-hypernova-id="b"><!--{encoded}--></script>'
        "</body></html>"
    )


def ok(listing: dict[str, Any]) -> HttpResponse:
    return HttpResponse(status=200, text=page_html(listing))


def items_of(listing: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = listing["data"]["state"]["products"]["items"]
    return items


def on_page(listing: dict[str, Any], page: int) -> dict[str, Any]:
    listing["data"]["state"]["products"]["pagination"]["page"] = page
    return listing


def make_adapter(*responses: HttpResponse) -> tuple[FootshopAdapter, FakeTransport]:
    transport = FakeTransport(responses=list(responses))
    return FootshopAdapter(FOOTSHOP_UA, transport), transport


def test_page_urls_use_path_pagination() -> None:
    adapter, _ = make_adapter()

    assert adapter.page_url(Segment(), 1) == SALE
    assert adapter.page_url(Segment(sex="men"), 1) == MEN
    assert adapter.page_url(Segment(sex="men"), 3) == MEN + "/page-3"
    with pytest.raises(ValueError, match="price"):
        adapter.page_url(Segment(sex="men", price=(0, 100)), 1)


async def test_the_start_page_is_the_first_root_page() -> None:
    adapter, transport = make_adapter(
        ok(load("listing_root")), ok(on_page(load("listing_root"), 2))
    )

    await adapter.warm_up()
    await adapter.warm_up()  # idempotent: the runner calls it again
    root = await adapter.fetch_page(Segment(), 1)
    await adapter.fetch_page(Segment(), 2)

    assert transport.gets == [SALE, SALE + "/page-2"]  # page 1 was not loaded twice
    assert root.count == 15192
    assert [(v.code, v.label, v.count) for v in root.facets.sex] == [
        ("male", "Men", 11265),
        ("female", "Women", 8953),
    ]
    assert root.facets.price_range is None  # no price segmentation for this shop
    assert root.category_tree is None


@pytest.mark.parametrize(("status", "error"), [(403, BlockedError), (429, BlockedError)])
async def test_a_refused_start_page_is_a_block(status: int, error: type[Exception]) -> None:
    adapter, _ = make_adapter(HttpResponse(status, "denied"))

    with pytest.raises(error):
        await adapter.warm_up()


async def test_a_broken_start_page_stops_the_run() -> None:
    adapter, _ = make_adapter(HttpResponse(404, "gone"))

    with pytest.raises(ScrapeError, match="404"):
        await adapter.warm_up()


def test_parse_page_normalizes_items() -> None:
    adapter, _ = make_adapter()
    result = adapter.parse_page(ok(load("listing_page")))

    assert result.count == 180
    assert result.invalid_items == 0
    assert len(result.items) == 6
    first = result.items[0]
    assert first.site == "footshop_ua"
    assert first.external_id == "537706"
    assert first.url == "https://www.footshop.ua/uk/category-55/537706-product-1.html"
    assert first.name == "Product 1"  # the title without the brand
    assert first.subtitle == "Color 1"  # the rest of the full name: the colorway
    assert (first.brand.external_id, first.brand.name) == ("12", "Brand 1")
    assert first.color == "color 1"
    assert [(c.external_id, c.name) for c in first.categories] == [("55", "Category 55")]
    assert (first.price_minor, first.price_regular_minor) == (371000, 529900)
    assert first.price_min30_minor is None
    assert first.discount_pct == 30  # 29.99% off: the shop's badge says "-30 %"
    assert first.available_for_buy
    assert [s.label for s in first.sizes][:3] == ["35.5", "36", "36 2/3"]
    size = first.sizes[0]
    assert (size.external_id, size.variation_id, size.ean) == ("154", "3804316", "0000003804316")
    assert (size.availability, size.in_stock) == ("IN_STOCK", True)


def test_discounts_match_the_shop_badges() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    badges = {str(i["id"]): i["price"]["sale"]["percents"] for i in items_of(listing)}

    result = adapter.parse_page(ok(listing))

    assert {i.external_id: i.discount_pct for i in result.items} == badges


def test_images_keep_their_extension_and_deduplicate() -> None:
    adapter, _ = make_adapter()
    result = adapter.parse_page(ok(load("listing_page")))
    first, second = result.items[0], result.items[1]

    assert first.image is not None
    assert first.image.name == "9000011.webp"
    assert [g.name for g in first.gallery] == ["9000011.webp", "9000013.webp"]
    assert [g.name for g in second.gallery] == ["9000021.jpg", "9000022.jpg", "9000023.jpg"]
    assert image_urls("footshop_ua", "9000011.webp", "") == (
        "https://static.ftshp.digital/img/p/9/0/0/0/0/1/1/9000011-full_product.webp",
        "https://static.ftshp.digital/img/p/9/0/0/0/0/1/1/9000011-thickbox.webp",
    )


def test_escaped_text_is_decoded() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    item = items_of(listing)[0]
    item["title"] = "A & B <Low>"
    item["name"] = "A & B <Low> Black"
    item["title_without_manufacturer"] = "A & B <Low>"

    first = adapter.parse_page(ok(listing)).items[0]

    assert (first.name, first.subtitle) == ("A & B <Low>", "Black")


def test_a_name_that_does_not_start_with_the_title_has_no_subtitle() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    items_of(listing)[0]["name"] = "Something else entirely"

    assert adapter.parse_page(ok(listing)).items[0].subtitle is None


def test_sold_out_items_and_empty_attributes() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    items_of(listing)[0]["sold_out"] = True
    items_of(listing)[1]["attributes"] = []  # how the shop encodes an empty map

    first, second, *_ = adapter.parse_page(ok(listing)).items

    assert not first.available_for_buy
    assert {s.in_stock for s in first.sizes} == {False}
    assert second.sizes == ()


def test_a_page_past_the_end_is_empty() -> None:
    adapter, _ = make_adapter()
    listing = on_page(load("listing_page"), 8)  # the shop serves its last page for page 9

    result = adapter.parse_page(ok(listing), page=9)

    assert result.items == ()
    assert result.count == 180


def test_a_bot_check_page_is_a_block() -> None:
    adapter, _ = make_adapter()
    html = '<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x">'

    with pytest.raises(BlockedError, match="bot check") as info:
        adapter.parse_page(HttpResponse(200, html))
    assert info.value.raw == html


def test_another_page_without_a_listing_is_a_contract_error() -> None:
    adapter, _ = make_adapter()

    with pytest.raises(ContractError, match="no product listing") as info:
        adapter.parse_page(HttpResponse(200, "<html><body>Home page</body></html>"))
    assert info.value.raw is not None
    assert "Home page" in info.value.raw


def test_a_changed_listing_format_fails_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    del listing["data"]["state"]["products"]["pagination"]

    with pytest.raises(ContractError, match="Unexpected product listing") as info:
        adapter.parse_page(ok(listing))
    assert info.value.raw is not None
    assert '"products"' in info.value.raw  # the listing JSON, not the whole page


def test_one_invalid_item_is_skipped() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    items_of(listing)[0]["price"]["currency_code"] = "EUR"

    result = adapter.parse_page(ok(listing))

    assert result.invalid_items == 1
    assert len(result.items) == 5


def test_many_invalid_items_stop_the_run() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    for item in items_of(listing)[:2]:
        del item["manufacturer"]

    with pytest.raises(ContractError, match="2 of 6 items"):
        adapter.parse_page(ok(listing))


@pytest.mark.parametrize(
    ("status", "error"),
    [(403, BlockedError), (429, BlockedError), (500, TransientError), (0, TransientError)],
)
def test_status_errors(status: int, error: type[Exception]) -> None:
    adapter, _ = make_adapter()

    with pytest.raises(error):
        adapter.parse_page(HttpResponse(status, "nope"))


def test_sections_are_the_root_segments() -> None:
    adapter, _ = make_adapter()
    root = adapter.parse_page(ok(load("listing_root")))

    segments = adapter.root_segments(root)

    assert segments == [Segment(sex="men"), Segment(sex="women"), Segment(sex="kids")]
    assert [adapter.gender_of(s) for s in segments] == [Gender.MEN, Gender.WOMEN, Gender.KIDS]
    assert adapter.gender_of(Segment()) == Gender(0)


def test_the_registry_builds_this_adapter() -> None:
    assert isinstance(create_adapter("footshop_ua", FakeTransport()), FootshopAdapter)


def test_extract_listing_ignores_other_scripts() -> None:
    assert extract_listing("<script>var x = 1;</script>") is None
    assert extract_listing(page_html({"a": "x > y & z"})) == '{"a": "x > y & z"}'
