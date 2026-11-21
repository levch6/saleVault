from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from salevault.api.app import create_app
from salevault.config import Settings
from salevault.domain.models import CategoryNode, Gender
from salevault.scraper.sites.registry import PRM
from tests.integration.helpers import product, seed_run

SITE = PRM.site_info


def factory_of(client: TestClient) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = client.app.state.factory  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path, frontend_dist=tmp_path / "dist"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    """Two runs. Run 2: `a` got cheaper, `e` is new, `d` was not seen (grace period)."""
    tree = [
        CategoryNode(external_id="100", name="Root", parent_external_id=None, depth=0),
        CategoryNode(external_id="101", name="Leaf", parent_external_id="100", depth=1),
    ]
    a = product("a", 100, regular=400, sizes=[("S", True), ("M", False)])
    b = product("b", 300, regular=600, min30=350, brand="2", sizes=[("M", True)])
    c = product("c", 900, regular=1000, sizes=[("L", True)])
    d = product("d", 50, regular=100, brand="3", sizes=[("ONE", True)])
    factory = factory_of(client)
    seed_run(
        factory, SITE, [(Gender.MEN, [a, c]), (Gender.WOMEN, [b, c]), (Gender.HOME, [d])], tree=tree
    )
    client.put(f"/api/favorites/{ids(client)['a']}")
    a2 = product("a", 80, regular=400, sizes=[("S", True), ("M", False)])
    e = product("e", 200, regular=1000, brand="2", sizes=[("S", True)])
    seed_run(factory, SITE, [(Gender.MEN, [a2, c, e]), (Gender.WOMEN, [b, c])], tree=tree)
    return client


def items(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/products", params=params)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()["items"]
    return result


def names(client: TestClient, **params: Any) -> list[str]:
    return [i["name"].removeprefix("Product ") for i in items(client, **params)]


def ids(client: TestClient) -> dict[str, int]:
    return {
        i["name"].removeprefix("Product "): i["id"] for i in items(client, include_inactive=True)
    }


def test_empty_catalog(client: TestClient) -> None:
    body = client.get("/api/products").json()

    assert body == {"items": [], "total": 0, "page": 1, "page_size": 60}


def test_default_sort_is_biggest_discount_first(seeded: TestClient) -> None:
    # e 80% (saves 800), a 80% (saves 320), b 50% (saves 300), d 50% (saves 50), c 10%
    assert names(seeded) == ["e", "a", "b", "d", "c"]


def test_card_shape(seeded: TestClient) -> None:
    card = next(i for i in items(seeded) if i["name"] == "Product b")

    assert card["site"] == "prm"
    assert (card["price"], card["price_regular"], card["price_min30"]) == (300, 600, 350)
    assert (card["discount_pct"], card["discount_min30_pct"], card["savings"]) == (50, 14, 300)
    assert card["currency"] == "UAH"
    assert card["brand"]["name"] == "Brand 2"
    assert card["genders"] == ["women"]
    assert card["sizes"] == [{"label": "M", "in_stock": True, "is_mine": False}]
    assert card["image"]["thumb"].startswith("https://img2.ans-media.com/i/316x478/b_F1.jpg")
    assert card["image"]["full"].startswith("https://img2.ans-media.com/i/1200x1800/")
    assert card["is_active"] is True


def test_unisex_items_match_both_genders(seeded: TestClient) -> None:
    assert sorted(names(seeded, gender="women")) == ["b", "c"]
    assert sorted(names(seeded, gender="men")) == ["a", "c", "e"]
    assert sorted(names(seeded, gender=["home", "women"])) == ["b", "c", "d"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"brand": None}, ["b", "e"]),  # brand id resolved in the test
        ({"price_min": 100, "price_max": 300}, ["b", "e"]),
        ({"discount_min": 50, "discount_max": 60}, ["b", "d"]),
        ({"q": "PRODUCT  E"}, ["e"]),  # casefolded, any whitespace
        ({"q": "brand 2"}, ["b", "e"]),
        ({"q": "100%_"}, []),  # LIKE wildcards are escaped
        ({"size": "S"}, ["a", "e"]),
        ({"size": "M"}, ["b"]),  # `a` has M, but out of stock
        ({"site": "nope"}, []),
        ({"site": "prm"}, ["a", "b", "c", "d", "e"]),
    ],
)
def test_filters(seeded: TestClient, params: dict[str, Any], expected: list[str]) -> None:
    if "brand" in params:
        brand_2 = next(i["brand"]["id"] for i in items(seeded) if i["brand"]["name"] == "Brand 2")
        params = {"brand": brand_2}

    assert sorted(names(seeded, **params)) == expected


def test_category_filter_includes_descendants(seeded: TestClient) -> None:
    facets = seeded.get("/api/facets").json()
    root = next(c for c in facets["categories"] if c["name"] == "Root")

    assert len(names(seeded, category=root["id"])) == 5


def test_my_sizes(seeded: TestClient) -> None:
    seeded.put("/api/settings", json={"my_sizes": ["M", " L ", "M"]})

    assert sorted(names(seeded, my_sizes=True)) == ["b", "c"]
    card = next(i for i in items(seeded) if i["name"] == "Product a")
    assert {s["label"]: s["is_mine"] for s in card["sizes"]} == {"S": False, "M": True}


def test_facets_combine_with_every_filter(seeded: TestClient) -> None:
    """Regression: EXISTS filters on tables the facet query joins itself (sizes, categories)."""
    seeded.put("/api/settings", json={"my_sizes": ["M", "L"]})
    root = next(c for c in seeded.get("/api/facets").json()["categories"] if c["name"] == "Root")

    for params in (
        {"my_sizes": True},
        {"size": "S"},
        {"category": root["id"]},
        {"my_sizes": True, "size": "M", "category": root["id"], "flags": "favorite"},
    ):
        response = seeded.get("/api/facets", params=params)
        assert response.status_code == 200, (params, response.text)

    facets = seeded.get("/api/facets", params={"my_sizes": True}).json()
    assert facets["total"] == 2
    assert {s["label"]: s["count"] for s in facets["sizes"]} == {"M": 1, "L": 1}


def test_badges_and_flags(seeded: TestClient) -> None:
    by_name = {i["name"]: i for i in items(seeded)}

    assert by_name["Product e"]["badges"] == ["new"]
    assert by_name["Product a"]["badges"] == ["price_drop"]
    assert by_name["Product a"]["prev_price"] == 100
    assert by_name["Product b"]["badges"] == []
    assert names(seeded, flags="new") == ["e"]
    assert names(seeded, flags="price_drop") == ["a"]
    assert names(seeded, flags="favorite") == ["a"]


def test_items_in_grace_stay_and_gone_items_are_hidden(seeded: TestClient) -> None:
    assert "d" in names(seeded), "missed once: still active"

    a = product("a", 80, regular=400)
    seed_run(factory_of(seeded), SITE, [(Gender.MEN, [a])])  # d: second miss -> inactive
    seed_run(factory_of(seeded), SITE, [(Gender.MEN, [a])])  # b, c, e: second miss

    assert names(seeded) == ["a"]
    assert sorted(names(seeded, include_inactive=True)) == ["a", "b", "c", "d", "e"]


def test_pagination_is_stable_and_complete(seeded: TestClient) -> None:
    pages = [
        seeded.get("/api/products", params={"page": p, "page_size": 2}).json() for p in (1, 2, 3)
    ]

    assert [p["total"] for p in pages] == [5, 5, 5]
    seen = [i["name"] for p in pages for i in p["items"]]
    assert len(seen) == len(set(seen)) == 5


@pytest.mark.parametrize(
    ("sort", "first"),
    [
        ("price_asc", "d"),
        ("price_desc", "c"),
        ("discount_min30_desc", "b"),
        ("savings_desc", "e"),
        ("newest", "e"),
    ],
)
def test_sorts(seeded: TestClient, sort: str, first: str) -> None:
    assert names(seeded, sort=sort)[0] == first


def test_facets_ignore_their_own_filter(seeded: TestClient) -> None:
    brand_2 = next(i["brand"]["id"] for i in items(seeded) if i["brand"]["name"] == "Brand 2")

    facets = seeded.get("/api/facets", params={"brand": brand_2}).json()

    assert facets["total"] == 2
    assert {b["name"]: b["count"] for b in facets["brands"]} == {
        "Brand 1": 2,
        "Brand 2": 2,
        "Brand 3": 1,
    }
    assert {g["value"]: g["count"] for g in facets["genders"]} == {
        "men": 1,
        "women": 1,
        "home": 0,
        "kids": 0,
    }
    assert facets["sites"] == [{"value": "prm", "label": "PRM", "count": 2}]
    assert {s["label"]: s["count"] for s in facets["sizes"]} == {"S": 1, "M": 1}
    assert facets["price"] == {"min": 200, "max": 300}
    assert facets["discount"] == {"min": 50, "max": 80}


def test_light_facets_skip_categories_and_sizes(seeded: TestClient) -> None:
    light = seeded.get("/api/facets", params={"heavy": False}).json()
    full = seeded.get("/api/facets").json()

    assert light["categories"] is None
    assert light["sizes"] is None
    assert {k: v for k, v in light.items() if k not in ("categories", "sizes")} == {
        k: v for k, v in full.items() if k not in ("categories", "sizes")
    }
    assert full["categories"]
    assert full["sizes"]


def test_facets_reflect_new_data(seeded: TestClient) -> None:
    before = seeded.get("/api/facets").json()["total"]
    seed_run(
        factory_of(seeded), SITE, [(Gender.MEN, [product("z", 10, regular=20)])], status="partial"
    )

    assert seeded.get("/api/facets").json()["total"] == before + 1, "cache is keyed by data version"


def test_product_detail(seeded: TestClient) -> None:
    detail = seeded.get(f"/api/products/{ids(seeded)['a']}").json()

    assert [h["price"] for h in detail["price_history"]] == [100, 80]
    assert detail["category_paths"] == [
        [
            {"id": detail["category_paths"][0][0]["id"], "name": "Root"},
            {"id": detail["category_paths"][0][1]["id"], "name": "Leaf"},
        ]
    ]
    assert detail["gallery"][0]["thumb"].endswith("a_F2.jpg?v=1")
    assert [(s["label"], s["availability"]) for s in detail["size_details"]] == [
        ("S", "IN_STOCK"),
        ("M", "OUT_OF_STOCK"),
    ]
    assert detail["is_favorite"] is True
    assert seeded.get("/api/products/999999").status_code == 404
    assert seeded.get("/api/products/999999").json()["code"] == "not_found"


def test_favorites_track_price_change(seeded: TestClient) -> None:
    favs = seeded.get("/api/favorites").json()

    assert [(f["product"]["name"], f["price_at_add"], f["price_change"]) for f in favs] == [
        ("Product a", 100, -20)
    ]
    a_id = favs[0]["product"]["id"]
    assert seeded.put(f"/api/favorites/{a_id}", json={"note": "wait for -90%"}).status_code == 204
    assert seeded.get("/api/favorites").json()[0]["note"] == "wait for -90%"
    assert seeded.delete(f"/api/favorites/{a_id}").status_code == 204
    assert seeded.delete(f"/api/favorites/{a_id}").status_code == 204, "idempotent"
    assert seeded.get("/api/favorites").json() == []
    assert seeded.put("/api/favorites/999999").status_code == 404


def test_settings_roundtrip(client: TestClient) -> None:
    assert client.get("/api/settings").json() == {"my_sizes": []}

    response = client.put("/api/settings", json={"my_sizes": ["43", " M", "", "43"]})

    assert response.json() == {"my_sizes": ["43", "M"]}
    assert client.put("/api/settings", json={}).json() == {"my_sizes": ["43", "M"]}, (
        "partial update"
    )
    assert client.put("/api/settings", json={"theme": "dark"}).status_code == 422


def test_unknown_query_parameters_are_rejected(client: TestClient) -> None:
    assert client.get("/api/products", params={"brnad": 1}).status_code == 422
    assert client.get("/api/products", params={"page_size": 500}).status_code == 422
