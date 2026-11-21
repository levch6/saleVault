import json
import re
from pathlib import Path
from typing import Any

import pytest

from salevault.domain.models import Gender
from salevault.scraper.base import HttpResponse, Segment
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError
from salevault.scraper.sites.modivo import ModivoAdapter, extract_listing
from salevault.scraper.sites.registry import MODIVO_UA, create_adapter, image_urls
from tests.fakes import FakeTransport

FIXTURES = Path(__file__).parent.parent / "fixtures" / "modivo"
ORIGIN = "https://modivo.ua"
SALE = f"{ORIGIN}/c/modivo/discount:~r-5-99"
MEN = Segment(sex="men")

# The shop's robots.txt for every user agent (2026-11-21).
DISALLOW = [
    "/login",
    "/wishlist",
    "/checkout",
    "/s/",
    "/customer",
    "/cdn-cgi",
    "/m-api/",
    "/t-api/",
    "/n-api/",
    "/c/*%26*",
    "/c/*tsina:*",
    "/activity*",
    "/auth/read-auth-tokens",
    "/c/*:*:*:*:*",
    "/c/*:*-*-*",
    "/*orderDir",
]
ALLOW = ["/*discount:~r-5-99*"]


def _matches(rule: str, path: str) -> bool:
    pattern = re.escape(rule).replace(r"\*", ".*")
    if pattern.endswith(r"\$"):
        pattern = pattern[:-2] + "$"
    return re.match(pattern, path) is not None


def allowed(url: str) -> bool:
    """The robots.txt semantics of RFC 9309 and Google: the longest matching rule wins, and
    Allow wins a tie."""
    path = url.removeprefix(ORIGIN)
    found = [(len(rule), True) for rule in ALLOW if _matches(rule, path)]
    found += [(len(rule), False) for rule in DISALLOW if _matches(rule, path)]
    return not found or max(found)[1]


def load(name: str = "listing_page") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def js(value: Any) -> str:
    """A JavaScript literal as devalue writes it: escaped non-ASCII text, "<" and "/"."""
    return json.dumps(value).replace("<", "\\u003C").replace("/", "\\u002F")


def page_html(listing: dict[str, Any], **extra: Any) -> str:
    """A catalog page whose state holds `listing` the way the shop's pages do: devalue's
    function form, the listing in `data[0]` and the product details in a store."""
    products = [{**card, **extra} for card in listing["products"]]
    script = (
        "(function(a,b,c,d){b.heading=d;b.listingDetails=a;b.products=c;"
        'return {layout:"default",data:[b],error:null,serverRendered:true,'
        "pinia:{searchCategory:{productsAnalytics:"
        + js(listing["productsAnalytics"])
        + ',url:"choloviky"}}}}('
        + js(listing["listingDetails"])
        + ",{},"
        + js(products)
        + ',"Sale"))'
    )
    return (
        '<!doctype html><html lang="uk"><head><title>Sale</title>'
        '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head>'
        '<body><div id="__nuxt"></div>'
        f"<script>window.__NUXT__={script};</script>"
        '<script src="/pwa/assets/app.js" defer></script></body></html>'
    )


def ok(listing: dict[str, Any]) -> HttpResponse:
    return HttpResponse(status=200, text=page_html(listing))


def make_adapter(*responses: HttpResponse) -> tuple[ModivoAdapter, FakeTransport]:
    transport = FakeTransport(responses=list(responses))
    return ModivoAdapter(MODIVO_UA, transport), transport


def test_page_urls_are_the_sale_of_each_section() -> None:
    adapter, _ = make_adapter()

    assert adapter.page_url(Segment(), 1) == SALE
    assert adapter.page_url(Segment(), 2) == f"{SALE}?p=2"
    assert adapter.page_url(MEN, 1) == f"{ORIGIN}/c/choloviky/discount:~r-5-99"
    assert adapter.page_url(Segment(sex="women"), 3) == f"{ORIGIN}/c/zhinky/discount:~r-5-99?p=3"
    assert adapter.page_url(Segment(sex="kids"), 1) == f"{ORIGIN}/c/dity/discount:~r-5-99"
    with pytest.raises(ValueError, match="price"):
        adapter.page_url(Segment(sex="men", price=(0, 100)), 1)


def test_no_url_the_adapter_loads_is_disallowed_by_robots_txt() -> None:
    adapter, _ = make_adapter()
    segments = [Segment(), *adapter.root_segments(adapter.parse_listing(load()))]

    urls = [adapter.page_url(s, page) for s in segments for page in (1, 2, 532, 886)]

    assert [url for url in urls if not allowed(url)] == []
    # They match a Disallow rule too; the longer Allow rule of the exact sale filter wins.
    assert all(any(_matches(rule, url.removeprefix(ORIGIN)) for rule in DISALLOW) for url in urls)
    assert not allowed(f"{ORIGIN}/c/zhinky/discount:~r-10-99")  # the menus' other filter
    assert not allowed(f"{ORIGIN}/c/zhinky/kolir:chornii/rozmir:m/discount:~r-10-99")
    assert not allowed(f"{ORIGIN}/m-api/catalog/products")
    assert not allowed(f"{ORIGIN}/s/jacket?q=jacket")


async def test_the_start_page_is_the_first_root_page() -> None:
    root_page_2 = load()
    root_page_2["listingDetails"]["currentPage"] = 2
    adapter, transport = make_adapter(ok(load()), ok(root_page_2))

    await adapter.warm_up()
    await adapter.warm_up()  # idempotent: the runner calls it again
    root = await adapter.fetch_page(Segment(), 1)
    second = await adapter.fetch_page(Segment(), 2)

    assert transport.gets == [SALE, f"{SALE}?p=2"]  # page 1 loaded once
    assert root.count == 17670
    assert len(second.items) == 6
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


def test_extract_listing_keeps_only_what_the_adapter_reads() -> None:
    listing = load()
    html = page_html(listing, openGraphImage=[{"src": "x"}], adTechEvents={"onView": []})

    assert extract_listing(html) == listing


def test_parse_page_normalizes_items() -> None:
    adapter, _ = make_adapter()
    result = adapter.parse_page(ok(load()))

    assert result.count == 17670
    assert result.invalid_items == 0
    assert len(result.items) == 6
    first = result.items[0]
    assert first.site == "modivo_ua"
    assert first.external_id == "0000306296176"
    assert first.url == f"{ORIGIN}/p/brand-1-product-1-0000306296176"
    assert (first.brand.external_id, first.brand.name) == ("Brand 1", "Brand 1")
    assert first.name == "Product 1"  # the kind of item; the card adds the color
    assert first.subtitle == "MODEL-0001 Color 1 Regular Fit"  # the rest of the full name
    assert first.color == "Color 1"
    assert first.categories == ()
    assert (first.price_minor, first.price_regular_minor) == (849900, 1199900)
    assert (first.price_min30_minor, first.discount_min30_pct) == (None, None)
    assert first.discount_pct == 29
    assert first.available_for_buy
    assert first.search_text == "brand 1 product 1 model-0001 color 1 regular fit color 1"


def test_discounts_truncate_like_the_shop() -> None:
    """1,599 of 1,699 is 5.9% and the shop shows 5%; 11,699 of 14,399 is 18.75%, shown as 18%."""
    adapter, _ = make_adapter()
    listing = load()

    result = adapter.parse_page(ok(listing))

    assert [i.discount_pct for i in result.items] == [29, 18, 5, 24, 29, 19]
    shop = [d["price"]["discount"] for d in listing["productsAnalytics"]]
    assert [f"{i.discount_pct}%" for i in result.items] == shop


def test_sizes_and_their_availability() -> None:
    adapter, _ = make_adapter()
    items = adapter.parse_page(ok(load())).items

    first, _, one_size, shoes, *_ = items
    assert [(s.label, s.availability, s.in_stock) for s in first.sizes] == [
        ("S", "IN_STOCK", True),
        ("M", "OUT_OF_STOCK", False),  # sold-out sizes are listed
        ("L", "IN_STOCK", True),
        ("XL", "IN_STOCK", True),
        ("XXL", "OUT_OF_STOCK", False),
    ]
    size = first.sizes[0]
    assert (size.external_id, size.variation_id, size.ean) == ("S", "0000306296176-S", None)
    assert [(s.external_id, s.label) for s in one_size.sizes] == [("NOSIZE", "One Size")]
    assert [s.label for s in shoes.sizes] == ["40", "41", "42", "43", "44", "45", "46"]
    assert shoes.sizes[1].availability == "LAST"  # few left


def test_the_filter_size_is_preferred_to_the_card_size() -> None:
    """The product card shows a women's XS as 34; the shop's size filter calls it XS."""
    adapter, _ = make_adapter()
    listing = load()
    variant = listing["productsAnalytics"][0]["variants"]["S"]
    variant["values"]["rozmiar_karta_produktu"]["value"]["label"] = "36"
    other = listing["productsAnalytics"][1]["variants"]["S"]
    del other["values"]["clothes_size"]
    other["values"]["rozmiar_karta_produktu"]["value"]["label"] = "36"
    listing["productsAnalytics"][2]["variants"]["NOSIZE"]["values"] = []

    first, second, third, *_ = adapter.parse_page(ok(listing)).items

    assert first.sizes[0].label == "S"
    assert second.sizes[0].label == "36"
    assert third.sizes[0].label == "NOSIZE"  # the variant's own size


def test_sizes_follow_the_shop_order_and_unknown_availability_is_not_in_stock() -> None:
    adapter, _ = make_adapter()
    listing = load()
    variants = listing["productsAnalytics"][0]["variants"]
    variants["S"]["sort_order"] = 9
    variants["L"]["availability"] = "preorder"

    first = adapter.parse_page(ok(listing)).items[0]

    assert [s.label for s in first.sizes] == ["M", "L", "XL", "XXL", "S"]
    assert (first.sizes[1].availability, first.sizes[1].in_stock) == ("PREORDER", False)


def test_an_item_without_sizes_in_stock_is_not_available() -> None:
    adapter, _ = make_adapter()
    listing = load()
    for variant in listing["productsAnalytics"][1]["variants"].values():
        variant["availability"] = "unavailable"
    listing["productsAnalytics"][2]["variants"] = []

    _, sold_out, no_sizes, *_ = adapter.parse_page(ok(listing)).items

    assert not sold_out.available_for_buy
    assert (no_sizes.sizes, no_sizes.available_for_buy) == ((), True)


def test_the_lowest_price_of_30_days_when_the_shop_shows_it() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["productsAnalytics"][0]["price"]["omnibus"]["amount"] = 9999

    first = adapter.parse_page(ok(listing)).items[0]

    assert (first.price_min30_minor, first.discount_min30_pct) == (999900, 15)


def test_missing_prices() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["productsAnalytics"][0]["price"]["regular"]["amount"] = None
    listing["productsAnalytics"][1]["price"]["promotional"] = {"amount": None}
    del listing["productsAnalytics"][2]["price"]["omnibus"]

    first, second, third, *_ = adapter.parse_page(ok(listing)).items

    assert (first.price_minor, first.price_regular_minor, first.discount_pct) == (849900, 849900, 0)
    assert (second.price_minor, second.discount_pct) == (1439900, 0)
    assert third.price_min30_minor is None


def test_an_item_without_any_price_is_skipped() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["productsAnalytics"][0]["price"] = {"regular": {"amount": None}}

    result = adapter.parse_page(ok(listing))

    assert (result.invalid_items, len(result.items)) == (1, 5)


def test_names_without_the_usual_parts() -> None:
    adapter, _ = make_adapter()
    listing = load()
    first, second, third = listing["products"][:3]
    first["designSystem"]["images"] = []
    first["mainProductImageSlug"] = None
    second["designSystem"]["name"] = "Product 2"  # no color part
    third["designSystem"]["name"] = " \N{MIDDLE DOT} Color 3"
    listing["productsAnalytics"][1]["color"] = None

    a, b, c, *_ = adapter.parse_page(ok(listing)).items

    assert (a.name, a.subtitle, a.image, a.gallery) == ("Product 1", None, None, ())
    assert (b.name, b.color) == ("Product 2", None)
    assert c.name == "\N{MIDDLE DOT} Color 3"


def test_three_part_names_keep_the_color() -> None:
    adapter, _ = make_adapter()

    fifth = adapter.parse_page(ok(load())).items[4]

    assert (fifth.name, fifth.color) == ("Product 5", "Color 5")


def test_escaped_text_is_decoded() -> None:
    """The state spells non-ASCII text, "/" and "<" as \\uXXXX escapes."""
    adapter, _ = make_adapter()
    listing = load()
    design = listing["products"][0]["designSystem"]
    name = "Product \N{LATIN SMALL LETTER E WITH ACUTE} </b>"
    design.update(brand="Brand & Co", name=f"{name} \N{MIDDLE DOT} X")

    first = adapter.parse_page(ok(listing)).items[0]

    assert (first.brand.name, first.name) == ("Brand & Co", name)


def test_images_and_their_sizes() -> None:
    adapter, _ = make_adapter()
    first = adapter.parse_page(ok(load())).items[0]

    name = "0/0/0/1/0001000100000000000000000000000000000000_01_TEST0001_M.jpg"
    assert first.image is not None
    assert (first.image.name, first.image.version) == (name, "")
    assert [g.name for g in first.gallery] == [
        name,
        name.replace("00010001", "00010002").replace("_01_", "_02_"),
        name.replace("00010001", "00010003").replace("_01_", "_03_"),
    ]
    assert image_urls("modivo_ua", name, "") == (
        f"https://img.modivo.cloud/product({name},webp)",
        f"https://img.modivo.cloud/zoomapp({name},webp)",
    )


def test_images_of_another_shape_are_ignored() -> None:
    adapter, _ = make_adapter()
    listing = load()
    card = listing["products"][0]
    card["mainProductImageSlug"] = None
    card["designSystem"]["images"] = [
        {"src": "https://elsewhere.test/productcard(0/0/0/1/a.jpg,jpg)/x.jpg", "alt": None},
        {"src": "https://img.modivo.cloud/marketing_card(banner.png,webp)", "alt": None},
        {"src": "https://img.modivo.cloud/productcard(0/0/0/1/a.jpg,jpg)", "alt": None},
    ]

    first = adapter.parse_page(ok(listing)).items[0]

    assert [g.name for g in first.gallery] == ["0/0/0/1/a.jpg"]


def test_a_page_past_the_end_is_empty() -> None:
    """Past the last page the shop answers 404; the catalog can shrink during a run."""
    adapter, _ = make_adapter()

    result = adapter.parse_page(HttpResponse(404, "<html>not found</html>"), page=300)

    assert (result.count, result.items) == (0, ())


def test_a_missing_first_page_is_an_error() -> None:
    adapter, _ = make_adapter()

    with pytest.raises(ContractError, match="404"):
        adapter.parse_page(HttpResponse(404, "<html>not found</html>"), page=1)


def test_a_page_other_than_the_one_asked_for_is_empty() -> None:
    adapter, _ = make_adapter()

    result = adapter.parse_page(ok(load()), page=2)  # the shop served page 1

    assert result.items == ()
    assert result.count == 17670


def test_a_new_page_size_fails_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["listingDetails"]["productsPerPage"] = 48

    with pytest.raises(ContractError, match="48 items per page"):
        adapter.parse_page(ok(listing))


def test_the_archive_holds_the_listing_only() -> None:
    adapter, _ = make_adapter()
    html = page_html(load(), openGraphImage=[{"src": "x"}])

    result = adapter.parse_page(HttpResponse(200, html))

    assert json.loads(result.raw) == load()
    assert "openGraphImage" not in result.raw


def test_another_currency_fails_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load()
    for card in listing["products"]:
        card["currency"] = "EUR"

    with pytest.raises(ContractError, match="6 of 6 items"):
        adapter.parse_page(ok(listing))


def test_an_item_without_details_is_skipped() -> None:
    adapter, _ = make_adapter()
    listing = load()
    del listing["productsAnalytics"][3]

    result = adapter.parse_page(ok(listing))

    assert result.invalid_items == 1
    assert "0000306230590" not in {i.external_id for i in result.items}


def test_details_are_matched_by_sku() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["productsAnalytics"].reverse()

    result = adapter.parse_page(ok(listing))

    assert [i.discount_pct for i in result.items] == [29, 18, 5, 24, 29, 19]


def test_a_product_link_of_another_shape_is_skipped() -> None:
    adapter, _ = make_adapter()
    listing = load()
    listing["products"][0]["designSystem"]["url"] = "https://elsewhere.test/p/x"

    result = adapter.parse_page(ok(listing))

    assert (result.invalid_items, len(result.items)) == (1, 5)


def test_a_listing_of_another_shape_fails_loudly() -> None:
    adapter, _ = make_adapter()
    listing = load()
    del listing["listingDetails"]["totalProducts"]

    with pytest.raises(ContractError, match="Unexpected product listing") as info:
        adapter.parse_page(ok(listing))
    assert info.value.raw is not None
    assert '"productsAnalytics"' in info.value.raw  # what the adapter read, not the page


def test_an_unreadable_state_fails_loudly() -> None:
    adapter, _ = make_adapter()
    html = "<html><script>window.__NUXT__=(function(a){return alert(a)}(1));</script></html>"

    with pytest.raises(ContractError, match="Unreadable page state") as info:
        adapter.parse_page(HttpResponse(200, html))
    assert info.value.raw == html


def test_a_bot_check_page_is_a_block() -> None:
    adapter, _ = make_adapter()
    html = '<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x">'

    with pytest.raises(BlockedError, match="bot check") as info:
        adapter.parse_page(HttpResponse(200, html))
    assert info.value.raw == html


def test_another_page_is_a_contract_error() -> None:
    adapter, _ = make_adapter()
    home = '<html><script>window.__NUXT__={layout:"default",data:[{}],pinia:{}};</script></html>'

    with pytest.raises(ContractError, match="no product listing") as info:
        adapter.parse_page(HttpResponse(200, home))
    assert info.value.raw == home


def test_many_invalid_items_stop_the_run() -> None:
    adapter, _ = make_adapter()
    listing = load()
    for card in listing["products"][:2]:
        card["designSystem"]["brand"] = ""

    with pytest.raises(ContractError, match="2 of 6 items"):
        adapter.parse_page(ok(listing))


@pytest.mark.parametrize(
    ("status", "error"),
    [(403, BlockedError), (429, BlockedError), (500, TransientError), (0, TransientError)],
)
def test_status_errors(status: int, error: type[Exception]) -> None:
    adapter, _ = make_adapter()

    with pytest.raises(error):
        adapter.parse_page(HttpResponse(status, "nope"), page=2)


def test_the_gender_sections_are_the_root_segments() -> None:
    adapter, _ = make_adapter()

    segments = adapter.root_segments(adapter.parse_listing(load()))

    assert [s.sex for s in segments] == ["men", "women", "kids"]
    assert [adapter.gender_of(s) for s in segments] == [Gender.MEN, Gender.WOMEN, Gender.KIDS]
    assert adapter.gender_of(Segment()) == Gender(0)


def test_the_registry_builds_this_adapter() -> None:
    assert isinstance(create_adapter("modivo_ua", FakeTransport()), ModivoAdapter)


def test_the_fixture_has_no_shop_text() -> None:
    text = (FIXTURES / "listing_page.json").read_text()

    assert text.isascii()
    assert not re.search(r"\\u04[0-9a-f]{2}", text)
