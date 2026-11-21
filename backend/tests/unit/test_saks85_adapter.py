import json
import re
from html import escape
from pathlib import Path
from typing import Any

import pytest

from salevault.domain.models import Gender
from salevault.scraper.base import HttpResponse, Segment
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError
from salevault.scraper.sites.registry import SAKS85, create_adapter, image_urls
from salevault.scraper.sites.saks85 import Saks85Adapter, extract_listing, money, product_id
from tests.fakes import FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures" / "saks85"
ORIGIN = "https://saks85.com"
SALE = f"{ORIGIN}/catalogue/special/rasprodazha/"
MEN_CLOTHING = f"{ORIGIN}/odyag/special/rasprodazha/stat/choloviche/"
LISTING = f"{ORIGIN}/index.php?route=product/category"

# The rules of the shop's robots.txt for every user agent that a catalog URL could match.
DISALLOW = [
    "/*?page=",
    "/*?limit=",
    "/*&limit=",
    "/*?sort=",
    "/*&sort=",
    "/*?order=",
    "/*&order=",
    "/*?filter=",
    "/*?route=extension/module/ocfilter",
    "/*?search=",
    "/*&search=",
    "/*?url=",
    "/*&url=",
    "/*?pages_count=",
]


def disallowed(url: str) -> bool:
    path = url.removeprefix(ORIGIN)
    return any(re.match(re.escape(rule).replace(r"\*", ".*"), path) for rule in DISALLOW)


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def card_html(card: dict[str, Any]) -> str:
    title = escape(card["title"])
    images = card["images"]
    imgs = "".join(
        f'<img class="catalog-card__{kind}" src="{escape(src)}" alt="{title}" title="{title}">'
        for kind, src in zip(("main", "secondary"), images, strict=False)
    )
    prev = (
        f'<span class="catalog-card__price-prev">{escape(card["price_regular"])}</span>'
        if card.get("price_regular")
        else ""
    )
    sizes = "".join(
        '<li><a class="catalog-card__size'
        + ("" if size["available"] else " catalog-card__size--disabled")
        + f'" >{escape(size["label"])}</a></li>\n'
        for size in card["sizes"]
    )
    return f"""
    <div class="catalog-card  catalog-card--has-sizes" >
        <div class="catalog-card__photo">
            <a href="{escape(card["url"])}" data-id="21618">
                {imgs}                </a>
        </div>
        <div class="catalog-card__bottom">
            <div class="catalog-card__brand"><a>{escape(card["brand"])}</a></div>
            <div class="catalog-card__title">{title}</div>
            <div class="catalog-card__price">
                {prev} {escape(card["price"])}
            </div>
            <div class="catalog-card__sizes">
                <div class="catalog-card__sizes-title">Sizes INT</div>
                <ul class="catalog-card__sizes-list list-unstyled">
                {sizes}
                </ul>
            </div>
        </div>
    </div>"""


def page_html(listing: dict[str, Any]) -> str:
    """A catalog page in the shop's markup, with the cards, heading and count of `listing`."""
    summary = listing["summary"]
    toolbar = (
        '<div class="row toolbar4 hidden"><div class="col-sm-6"><ul class="pagination">'
        '<li class="active"><span>1</span></li><li><a href="?page=2">2</a></li></ul></div>'
        f'<div class="col-sm-6 text-right">Showing {summary["first"]} to {summary["last"]} '
        f"of {summary['total']} ({summary['pages']} pages)</div></div>"
        if summary
        else "<p>No products</p>"
    )
    heading = listing["heading"]
    return (
        '<!DOCTYPE html><html lang="uk"><head><title>Catalog</title>'
        '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head><body>'
        '<input type="hidden" value="G-1" class="ecommerce_ga4_identifier" />'
        f'<input type="hidden" value="{listing["currency"]}" class="currency_ecommerce_code" />'
        '<div class="col-sm-6 text-right">Call us 9:00 to 19:00</div>'
        + (f'<h1 class="catalog__title">{escape(heading)}</h1>' if heading else "")
        + '<div class="custom-products"><div class="catalog__cards">'
        + "".join(card_html(card) for card in listing["cards"])
        + "</div>"
        + toolbar
        + "</div></body></html>"
    )


def ok(listing: dict[str, Any]) -> HttpResponse:
    return HttpResponse(status=200, text=page_html(listing))


def make_adapter(*responses: HttpResponse) -> tuple[Saks85Adapter, FakeTransport]:
    transport = FakeTransport(responses=list(responses))
    return Saks85Adapter(SAKS85, transport), transport


MEN = Segment(sex="men-clothing")


def test_page_1_is_the_menu_path_and_later_pages_the_non_seo_url() -> None:
    adapter, _ = make_adapter()

    assert adapter.page_url(Segment(), 1) == SALE
    assert adapter.page_url(Segment(), 2) == (
        f"{LISTING}&path=0&filter_ocfilter=10010:4252492525&page=2"
    )
    assert adapter.page_url(MEN, 1) == MEN_CLOTHING
    assert adapter.page_url(MEN, 3) == (
        f"{LISTING}&path=69&filter_ocfilter=10010:4252492525;10024:4252492559&page=3"
    )
    assert adapter.page_url(Segment(sex="women-home"), 1) == (
        f"{ORIGIN}/aromaty-dlya-domu-ta-avto/special/rasprodazha/stat/zhinoche/"
    )
    with pytest.raises(ValueError, match="price"):
        adapter.page_url(Segment(sex="men-clothing", price=(0, 100)), 1)


def test_no_url_the_adapter_loads_is_disallowed_by_robots_txt() -> None:
    adapter, _ = make_adapter()
    segments = [Segment(), *adapter.root_segments(adapter.parse_listing(load("listing_root")))]

    urls = [adapter.page_url(s, page) for s in segments for page in (1, 2, 240)]

    assert [url for url in urls if disallowed(url)] == []
    assert disallowed(SALE + "?page=2")  # the shop's own pagination links
    assert disallowed(f"{LISTING}&path=0&limit=100")


async def test_the_start_page_is_the_first_root_page() -> None:
    root_page_2 = load("listing_root")
    root_page_2["summary"].update(first=13, last=24)
    adapter, transport = make_adapter(ok(load("listing_root")), ok(root_page_2))

    await adapter.warm_up()
    await adapter.warm_up()  # idempotent: the runner calls it again
    root = await adapter.fetch_page(Segment(), 1)
    second = await adapter.fetch_page(Segment(), 2)

    assert transport.gets == [SALE, adapter.page_url(Segment(), 2)]  # page 1 loaded once
    assert root.count == 2873
    assert len(second.items) == 2
    assert root.facets.sex == ()
    assert root.facets.price_range is None  # no price segmentation for this shop
    assert root.category_tree is None


@pytest.mark.parametrize("status", [403, 429])
async def test_a_refused_start_page_is_a_block(status: int) -> None:
    adapter, _ = make_adapter(HttpResponse(status, "denied"))

    with pytest.raises(BlockedError):
        await adapter.warm_up()


async def test_a_broken_start_page_stops_the_run() -> None:
    adapter, _ = make_adapter(HttpResponse(404, "gone"))

    with pytest.raises(ScrapeError, match="404"):
        await adapter.warm_up()


def test_extract_listing_reads_the_cards_of_a_page() -> None:
    listing = load("listing_page")

    assert extract_listing(page_html(listing)) == listing


def test_parse_page_normalizes_items() -> None:
    adapter, _ = make_adapter()
    result = adapter.parse_page(ok(load("listing_page")), MEN)

    assert result.count == 1254
    assert result.invalid_items == 0
    assert len(result.items) == 6
    first = result.items[0]
    assert first.site == "saks85"
    assert first.external_id == "product-1_test-0001"  # the product's path: cards have no id
    assert first.url == f"{ORIGIN}/product-1_test-0001"
    assert (first.name, first.subtitle, first.color) == ("Product 1", None, None)
    assert (first.brand.external_id, first.brand.name) == ("Brand 1", "Brand 1")
    assert [(c.external_id, c.name) for c in first.categories] == [("69", "Category")]
    assert (first.price_minor, first.price_regular_minor) == (695200, 869000)
    assert first.price_min30_minor is None
    assert first.discount_pct == 20
    assert first.available_for_buy
    assert [(s.label, s.in_stock) for s in first.sizes] == [
        ("M", False),
        ("L", False),
        ("XL", False),
        ("XXL", True),
    ]
    size = first.sizes[0]
    assert (size.external_id, size.variation_id, size.ean) == ("M", "M", None)
    assert size.availability == "OUT_OF_STOCK"
    assert first.sizes[-1].availability == "IN_STOCK"


def test_discounts_are_whole_percents_of_the_regular_price() -> None:
    adapter, _ = make_adapter()

    result = adapter.parse_page(ok(load("listing_page")), MEN)

    assert [i.discount_pct for i in result.items] == [20, 20, 10, 20, 20, 20]


def test_root_items_have_no_category() -> None:
    adapter, _ = make_adapter()

    result = adapter.parse_page(ok(load("listing_root")))

    assert [i.categories for i in result.items] == [(), ()]


def test_images_and_their_sizes() -> None:
    adapter, _ = make_adapter()
    first = adapter.parse_page(ok(load("listing_page")), MEN).items[0]

    name = "catalog/pim/product/TEST-0001/test-0001-1.webp"
    assert first.image is not None
    assert first.image.name == name
    assert [g.name for g in first.gallery] == [name, name.replace("-1.", "-2.")]
    assert image_urls("saks85", name, "") == (
        f"{ORIGIN}/image/cache/catalog/pim/product/TEST-0001/test-0001-1-352x530.webp",
        f"{ORIGIN}/image/cache/catalog/pim/product/TEST-0001/test-0001-1-1200x1800.webp",
    )


def test_placeholder_images_are_ignored() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["cards"][0]["images"] = [f"{ORIGIN}/image/cache/placeholder-352x530.png"]

    first = adapter.parse_page(ok(listing), MEN).items[0]

    assert (first.image, first.gallery) == (None, ())


def test_escaped_text_is_decoded() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["cards"][0].update(title="A & B <Low>", brand="Brand & Co")

    first = adapter.parse_page(ok(listing), MEN).items[0]

    assert (first.name, first.brand.name) == ("A & B <Low>", "Brand & Co")


def test_product_ids_come_from_the_path() -> None:
    long_path = "women_brown_crossbody_bag_with_a_pattern_and_leather_trim_21x_" + "c0025-m0019"

    assert product_id("men_hoodie_hm5800158-595") == "men_hoodie_hm5800158-595"
    assert product_id("suit_blazer%2Bhose_682400600-399") == "suit_blazer+hose_682400600-399"
    long_id = product_id(long_path)
    assert len(long_id) == 64
    assert long_id.startswith(long_path[:47] + "~")
    assert long_id == product_id(long_path)
    assert long_id != product_id(long_path[:-1] + "8")


def test_sold_out_items_and_repeated_sizes() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    for size in listing["cards"][0]["sizes"]:
        size["available"] = False
    listing["cards"][1]["sizes"] = [{"label": "OS", "available": True}] * 2
    listing["cards"][2]["sizes"] = []

    first, second, third, *_ = adapter.parse_page(ok(listing), MEN).items

    assert not first.available_for_buy
    assert [s.label for s in second.sizes] == ["OS"]
    assert (third.sizes, third.available_for_buy) == ((), True)


def test_an_item_without_a_regular_price_has_no_discount() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["cards"][0]["price_regular"] = None

    first = adapter.parse_page(ok(listing), MEN).items[0]

    assert (first.price_regular_minor, first.discount_pct) == (695200, 0)


@pytest.mark.parametrize(
    ("text", "amount"),
    [("6 952 UAH", "6952"), ("36\u00a0864 UAH", "36864"), ("1 234,50 UAH", "1234.50")],
)
def test_money_reads_the_price_as_shown(text: str, amount: str) -> None:
    assert str(money(text)) == amount


def test_an_empty_listing_has_no_items() -> None:
    """An empty section, or a page past the end: the shop shows no products and no count."""
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing.update(cards=[], summary=None)

    result = adapter.parse_page(ok(listing), MEN, page=106)

    assert (result.count, result.items) == (0, ())


def test_a_page_other_than_the_one_asked_for_is_empty() -> None:
    adapter, _ = make_adapter()

    result = adapter.parse_page(ok(load("listing_page")), MEN, page=2)  # the shop served page 1

    assert result.items == ()
    assert result.count == 1254


def test_cards_without_a_count_fail_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["summary"] = None

    with pytest.raises(ContractError, match="no item count") as info:
        adapter.parse_page(ok(listing), MEN)
    assert info.value.raw is not None
    assert '"cards"' in info.value.raw  # what the adapter read, not the whole page


def test_another_currency_fails_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["currency"] = "EUR"

    with pytest.raises(ContractError, match="currency"):
        adapter.parse_page(ok(listing), MEN)


def test_a_bot_check_page_is_a_block() -> None:
    adapter, _ = make_adapter()
    html = '<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x">'

    with pytest.raises(BlockedError, match="bot check") as info:
        adapter.parse_page(HttpResponse(200, html))
    assert info.value.raw == html


def test_another_page_is_a_contract_error() -> None:
    adapter, _ = make_adapter()

    with pytest.raises(ContractError, match="no product listing") as info:
        adapter.parse_page(HttpResponse(200, "<html><body>Home page</body></html>"))
    assert info.value.raw is not None
    assert "Home page" in info.value.raw


def test_one_invalid_item_is_skipped() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    listing["cards"][0]["url"] = "https://elsewhere.test/product"

    result = adapter.parse_page(ok(listing), MEN)

    assert result.invalid_items == 1
    assert len(result.items) == 5


def test_many_invalid_items_stop_the_run() -> None:
    adapter, _ = make_adapter()
    listing = load("listing_page")
    for card in listing["cards"][:2]:
        card["price"] = "on request"

    with pytest.raises(ContractError, match="2 of 6 items"):
        adapter.parse_page(ok(listing), MEN)


@pytest.mark.parametrize(
    ("status", "error"),
    [(403, BlockedError), (429, BlockedError), (500, TransientError), (0, TransientError)],
)
def test_status_errors(status: int, error: type[Exception]) -> None:
    adapter, _ = make_adapter()

    with pytest.raises(error):
        adapter.parse_page(HttpResponse(status, "nope"))


def test_every_gender_in_every_category_is_a_root_segment() -> None:
    adapter, _ = make_adapter()

    segments = adapter.root_segments(adapter.parse_listing(load("listing_root")))

    assert [s.sex for s in segments] == [
        "men-clothing",
        "men-shoes",
        "men-accessories",
        "men-home",
        "women-clothing",
        "women-shoes",
        "women-accessories",
        "women-home",
    ]
    assert {adapter.gender_of(s) for s in segments[:4]} == {Gender.MEN}
    assert {adapter.gender_of(s) for s in segments[4:]} == {Gender.WOMEN}
    assert adapter.gender_of(Segment()) == Gender(0)


def test_the_registry_builds_this_adapter() -> None:
    assert isinstance(create_adapter("saks85", FakeTransport()), Saks85Adapter)
