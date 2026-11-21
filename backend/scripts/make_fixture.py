"""Turn an archived raw API response into a small, anonymized test fixture.

Usage:
    uv run python scripts/make_fixture.py RAW.json.gz OUT.json [--items N]

Keeps the structure, ids, prices, sizes and availability. Replaces shop text (names, brands,
categories, labels, URLs, image names, EANs) with neutral English placeholders, so fixtures
can live in a public repository.
"""

import argparse
import copy
import gzip
import json
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
    return found


def pick_diverse(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    covered: set[str] = set()
    for item in items:
        if len(picked) < n and _features(item) - covered:
            picked.append(item)
            covered |= _features(item)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--items", type=int, default=6)
    args = parser.parse_args()

    with gzip.open(args.raw, "rt", encoding="utf-8") as fh:
        page = json.load(fh)

    brands: dict[str, str] = {}
    items = [
        anonymize_item(item, idx, brands)
        for idx, item in enumerate(pick_diverse(page["items"], args.items), start=1)
    ]
    fixture = {key: page[key] for key in KEEP_TOP_LEVEL if key in page}
    fixture["filters"] = anonymize_filters(page.get("filters", []))
    fixture["items"] = items

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} items to {args.out}")


if __name__ == "__main__":
    main()
