"""Turn an archived raw response into a small, anonymized test fixture.

Usage:
    uv run python scripts/make_fixture.py RAW.json.gz OUT.json [--items N]

Works with both archive formats: the Answear platform's API responses and the product listings
taken from Footshop's catalog pages. Keeps the structure, ids, prices, sizes and availability.
Replaces shop text (names, brands, categories, labels, URLs, image names, EANs) with neutral
English placeholders, so fixtures can live in a public repository.
"""

import argparse
import copy
import gzip
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

SEX_LABELS = {"D": "Women", "M": "Men", "H": "Home", "K": "Kids"}
KEEP_TOP_LEVEL = ("count", "sortingOrder", "urlFilters", "success")


def _features(item: dict[str, Any]) -> set[str]:
    """Traits worth covering in tests; used to pick a diverse sample."""
    found = set()
    if item.get("priceMinimal") not in (None, item.get("priceRegular")):
        found.add("min30_differs")
    if not any(b.get("type") == "percentage" for b in item.get("badges", [])):
        found.add("no_percentage_badge")
    availability = {s["variation"]["availability"] for s in item.get("allSizes", [])}
    found.update(f"size_{a}" for a in availability)
    if len(item.get("allSizes", [])) <= 1:
        found.add("single_size")
    if len(item.get("categories", [])) > 4:
        found.add("several_category_paths")
    return found


def pick_diverse(
    items: list[dict[str, Any]],
    n: int,
    features: Callable[[dict[str, Any]], set[str]] = _features,
) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    covered: set[str] = set()
    for item in items:
        if len(picked) < n and features(item) - covered:
            picked.append(item)
            covered |= features(item)
    for item in items:
        if len(picked) >= n:
            break
        if item not in picked:
            picked.append(item)
    return picked


def anonymize_item(item: dict[str, Any], idx: int, brands: dict[str, str]) -> dict[str, Any]:
    item = copy.deepcopy(item)
    code = f"TEST-{idx:04d}"
    brand = item["productBrand"]
    brand_name = brands.setdefault(str(brand["id"]), f"Brand {len(brands) + 1}")
    brand.update(name=brand_name, slug=brand_name.lower().replace(" ", "-"), logo="logo/test")

    item["name"] = f"{brand_name} product {idx}"
    item["frontName"] = f"Product {idx}"
    item["subtitle"] = f"color {idx} model {code}"
    item["slug"] = f"product-{idx}"
    item["url"] = f"/p/product-{idx}-{item['id']}"
    item["frontendUuid"] = code
    item["pbbCode"] = code
    if isinstance(item.get("color"), dict):
        item["color"]["name"] = f"color {idx}"
    for category in item.get("categories", []):
        category["name"] = f"Category {category['id']}"
    for size in item.get("allSizes", []):
        size["variation"]["ean"] = f"{size['variation']['id']:0>13}"
        if not size["name"].isascii():  # the shop's own words, e.g. "one size" in Ukrainian
            size["name"] = "One size"
    for key in ("badges", "badgesFront"):
        for badge in item.get(key) or []:
            if badge.get("type") != "percentage":  # promo codes and campaign names
                badge["text"] = "Promo"

    images = item.get("productImages", {})
    counter = 0
    for key in ("mainImage", "btlImage"):
        if isinstance(images.get(key), dict):
            counter += 1
            images[key]["name"] = f"{code}_F{counter}.avif"
    for image in images.get("galleryImages", []):
        counter += 1
        image["name"] = f"{code}_F{counter}.avif"
    return item


def anonymize_filters(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in filters:
        f = copy.deepcopy(raw)
        name = f.get("name")
        if name == "sex":
            for item in f["items"]:
                item["label"] = SEX_LABELS.get(item["value"], f"Section {item['value']}")
        elif name == "price":
            pass
        elif name == "color":
            # One unrelated facet stays, to prove the adapter ignores what it doesn't need.
            f["items"] = [
                {**item, "label": f"color {i}"} for i, item in enumerate(f["items"][:3], start=1)
            ]
        else:
            continue
        f["label"] = str(name).capitalize()
        f.pop("param", None)
        out.append(f)
    return out


def anonymize_tree(tree: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the branches the sample items use (plus one unrelated branch), rename every node."""
    used = {str(c["id"]) for item in items for c in item.get("categories", [])}
    spare_kept = False

    def prune(node: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal spare_kept
        children = [kept for child in node.get("children", []) if (kept := prune(child))]
        relevant = str(node["id"]) in used or children
        if not relevant and not spare_kept and node.get("children") == []:
            spare_kept = True  # one leaf nobody uses, to prove unused nodes are stored too
            relevant = True
        if not relevant:
            return None
        return {
            "id": node["id"],
            "name": f"Category {node['id']}",
            "slug": f"category-{node['id']}",
            "children": children,
        }

    return {"items": [kept for root in tree.get("items", []) if (kept := prune(root))]}


# --- Footshop catalog pages ------------------------------------------------------------------

FOOTSHOP_SEX_LABELS = {"male": "Men", "female": "Women"}
FOOTSHOP_IMAGE = re.compile(r"/img/p/(?:\d/)+(\d+)-([a-z_]+)\.([a-z]+)$")


def _footshop_features(item: dict[str, Any]) -> set[str]:
    found = {"ext_" + str(item.get("image", "")).rsplit(".", 1)[-1]}
    variants = (item.get("attributes") or {}).get("variants", [])
    found.add("single_size" if len(variants) <= 1 else "several_sizes")
    if item.get("image_woman"):
        found.add("image_woman")
    if not str(item.get("name", "")).startswith(str(item.get("title"))):
        found.add("title_not_in_name")
    return found


def _footshop_image(url: str, fake_id: int) -> str:
    match = FOOTSHOP_IMAGE.search(url)
    if not url or match is None:
        return url
    folder = "/".join(str(fake_id))
    return f"https://static.ftshp.digital/img/p/{folder}/{fake_id}-{match[2]}.{match[3]}"


def anonymize_footshop_item(
    item: dict[str, Any], idx: int, brands: dict[str, str]
) -> dict[str, Any]:
    item = copy.deepcopy(item)
    brand = item["manufacturer"]
    brand_name = brands.setdefault(str(brand["id"]), f"Brand {len(brands) + 1}")
    brand["name"] = brand_name
    title = f"{brand_name} Product {idx}"
    keep_title_in_name = str(item.get("name", "")).startswith(str(item.get("title")))
    item["title"] = title
    item["title_without_manufacturer"] = f"Product {idx}"
    item["name"] = f"{title} Color {idx}" if keep_title_in_name else f"Other name {idx}"
    item["code"] = f"TEST-{idx:04d}"
    item["code_original"] = ""
    item["description"] = ""
    item["color"] = item["color_en"] = f"color {idx}"
    category = item.get("main_category") or {}
    if category:
        cid = category["id"]
        category.update(
            name=f"Category {cid}",
            name_en=f"Category {cid}",
            short_name="",
            short_name_en="",
            slug=f"category-{cid}",
            url=f"{cid}-category-{cid}",
        )
        item["category_name_en"] = f"Category {cid}"
    item["url"] = f"category-{category.get('id', 0)}/{item['id']}-product-{idx}.html"
    item["breadcrumbs"] = []
    item["stickers"] = []
    item["video"] = []
    item["badges"] = [b for b in item.get("badges", []) if b.get("id") == "sale"]
    item["public_voucher"] = None
    item["boosting"] = None
    for key in ("messages", "value_formatted", "value_without_reduction_formatted"):
        item["price"].pop(key, None)
    for n, key in enumerate(("image", "image_woman", "last_image"), start=1):
        item[key] = _footshop_image(str(item.get(key) or ""), 9_000_000 + idx * 10 + n)
    for variant in (item.get("attributes") or {}).get("variants", []):
        size = re.search(r"size=(\d+)", variant.get("url", ""))
        variant["url"] = item["url"] + (f"?size={size[1]}" if size else "")
        variant["ean"] = f"{variant['package_id']:0>13}"
        if not variant["name"].isascii():
            variant["name"] = "One size"
    return item


def footshop_fixture(page: dict[str, Any], n: int) -> dict[str, Any]:
    state = page["data"]["state"]
    products = state["products"]
    brands: dict[str, str] = {}
    picked = pick_diverse(products["items"], n, features=_footshop_features)
    items = [anonymize_footshop_item(item, i, brands) for i, item in enumerate(picked, start=1)]
    filters: dict[str, Any] = {}
    if isinstance(state["filters"].get("sex"), dict):
        sex = copy.deepcopy(state["filters"]["sex"])
        sex["name"] = "Sex"
        for value in sex["items"]:
            value["name"] = FOOTSHOP_SEX_LABELS.get(value["id"], f"Section {value['id']}")
        filters["sex"] = sex
    if isinstance(state["filters"].get("color"), dict):
        # One unrelated facet stays, to prove the adapter ignores what it doesn't need.
        color = copy.deepcopy(state["filters"]["color"])
        color["name"] = "Color"
        color["items"] = [
            {**value, "name": f"color {i}", "name_en": f"color {i}"}
            for i, value in enumerate(color["items"][:3], start=1)
        ]
        filters["color"] = color
    return {
        "data": {
            "state": {
                "listing_type": state.get("listing_type"),
                "listing_type_id": state.get("listing_type_id"),
                "filters": filters,
                "products": {
                    "total": products["total"],
                    "pagination": products["pagination"],
                    "items": items,
                },
            }
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--items", type=int, default=6)
    args = parser.parse_args()

    with gzip.open(args.raw, "rt", encoding="utf-8") as fh:
        page = json.load(fh)

    if isinstance(page.get("data"), dict) and "state" in page["data"]:
        fixture = footshop_fixture(page, args.items)
        _write(args.out, fixture)
        print(f"Wrote {len(fixture['data']['state']['products']['items'])} items to {args.out}")
        return

    brands: dict[str, str] = {}
    items = [
        anonymize_item(item, idx, brands)
        for idx, item in enumerate(pick_diverse(page["items"], args.items), start=1)
    ]
    fixture = {key: page[key] for key in KEEP_TOP_LEVEL if key in page}
    fixture["filters"] = anonymize_filters(page.get("filters", []))
    if isinstance(page.get("categoryTree"), dict):
        fixture["categoryTree"] = anonymize_tree(page["categoryTree"], items)
    fixture["items"] = items

    _write(args.out, fixture)
    print(f"Wrote {len(items)} items to {args.out}")


def _write(path: Path, fixture: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
