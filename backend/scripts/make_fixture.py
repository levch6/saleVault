"""Turn an archived raw response into a small, anonymized test fixture.

Usage:
    uv run python scripts/make_fixture.py RAW.json.gz OUT.json [--items N]

Works with every archive format: the Answear platform's API responses, the product listings
taken from Footshop's catalog pages, the product cards read from Saks85's catalog pages and the
listings read from the state of Modivo's catalog pages.
Keeps the structure, ids, prices, sizes and availability.
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


# --- Saks85 catalog pages (the product cards the adapter read from a page) ---------------------

SAKS85_ORIGIN = "https://saks85.com"


def _saks85_features(card: dict[str, Any]) -> set[str]:
    sizes = card.get("sizes", [])
    found = {"single_size" if len(sizes) <= 1 else "several_sizes"}
    found.update("size_" + ("in" if s.get("available") else "out") for s in sizes)
    if len(card.get("images", [])) < 2:
        found.add("one_image")
    if "%" in str(card.get("url")):
        found.add("encoded_url")
    return found


def _ascii_price(text: str) -> str:
    """Keep the digits and spacing of a price, replace the currency word."""
    return re.sub(r"[^\x00-\x7f]+", "UAH", text)


def anonymize_saks85_card(card: dict[str, Any], idx: int, brands: dict[str, str]) -> dict[str, Any]:
    card = copy.deepcopy(card)
    code = f"test-{idx:04d}"
    card["brand"] = brands.setdefault(str(card.get("brand")), f"Brand {len(brands) + 1}")
    card["title"] = f"Product {idx}"
    card["url"] = f"{SAKS85_ORIGIN}/product-{idx}_{code}"
    card["price"] = _ascii_price(str(card.get("price", "")))
    if card.get("price_regular"):
        card["price_regular"] = _ascii_price(str(card["price_regular"]))
    card["images"] = [
        f"{SAKS85_ORIGIN}/image/cache/catalog/pim/product/{code.upper()}/{code}-{n}-352x530.webp"
        for n, _ in enumerate(card.get("images", []), start=1)
    ]
    for size in card.get("sizes", []):
        if not str(size.get("label", "")).isascii():
            size["label"] = "One size"
    return card


def saks85_fixture(page: dict[str, Any], n: int) -> dict[str, Any]:
    brands: dict[str, str] = {}
    picked = pick_diverse(page["cards"], n, features=_saks85_features)
    return {
        "heading": "Category" if page.get("heading") else None,
        "currency": page.get("currency"),
        "summary": page.get("summary"),
        "cards": [anonymize_saks85_card(c, i, brands) for i, c in enumerate(picked, start=1)],
    }


# --- Modivo catalog pages (the listing the adapter read from a page's state) -------------------

MODIVO_IMAGES = "https://img.modivo.cloud"


def _modivo_features(pair: dict[str, Any]) -> set[str]:
    card, details = pair["card"], pair["details"] or {}
    variants = details.get("variants") or {}
    found = {f"size_{v.get('availability')}" for v in variants.values()}
    found.add("single_size" if len(variants) <= 1 else "several_sizes")
    found.update(f"values_{key}" for v in variants.values() for key in v.get("values") or {})
    if str(card.get("designSystem", {}).get("name")).count(" \N{MIDDLE DOT} ") > 1:
        found.add("three_part_name")
    return found


def _modivo_image(idx: int, n: int) -> str:
    """A path in the CDN's form: four folders from the hash, then the file name."""
    digest = f"{idx:04x}{n:04x}".ljust(40, "0")
    return f"{'/'.join(digest[:4])}/{digest}_{n:02d}_TEST{idx:04d}_M.jpg"


def anonymize_modivo_pair(
    pair: dict[str, Any], idx: int, brands: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    card, details = copy.deepcopy(pair["card"]), copy.deepcopy(pair["details"])
    design = card["designSystem"]
    brand = brands.setdefault(str(design.get("brand")), f"Brand {len(brands) + 1}")
    sku = card["sku"]
    parts = str(design.get("name")).count(" \N{MIDDLE DOT} ")
    design["brand"] = brand
    design["name"] = f"Product {idx} \N{MIDDLE DOT} Color {idx}" + (
        " \N{MIDDLE DOT} Regular Fit" if parts > 1 else ""
    )
    slug = f"{brand.lower().replace(' ', '-')}-product-{idx}-{sku}"
    design["url"] = f"/p/{slug}"
    alt = f"{brand} {brand} Product {idx} MODEL-{idx:04d} Color {idx} Regular Fit"
    design["images"] = [
        {"src": f"{MODIVO_IMAGES}/productcard({_modivo_image(idx, n)},jpg)/{slug}.jpg", "alt": alt}
        for n, _ in enumerate((design.get("images") or [])[:3], start=1)  # three are enough
    ]
    card["mainProductImageSlug"] = _modivo_image(idx, 1) if design["images"] else None
    if details is not None:
        details["color"] = f"Color {idx}"
        for variant in (details.get("variants") or {}).values():
            for value in (variant.get("values") or {}).values():
                if not str(value["value"]["label"]).isascii():
                    value["value"]["label"] = "One size"
    return card, details


def modivo_fixture(page: dict[str, Any], n: int) -> dict[str, Any]:
    details = {d.get("sku"): d for d in page["productsAnalytics"]}
    pairs = [{"card": c, "details": details.get(c.get("sku"))} for c in page["products"]]
    brands: dict[str, str] = {}
    picked = pick_diverse(pairs, n, features=_modivo_features)
    anonymized = [anonymize_modivo_pair(p, i, brands) for i, p in enumerate(picked, start=1)]
    return {
        "listingDetails": page["listingDetails"],
        "products": [card for card, _ in anonymized],
        "productsAnalytics": [d for _, d in anonymized if d is not None],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--items", type=int, default=6)
    args = parser.parse_args()

    with gzip.open(args.raw, "rt", encoding="utf-8") as fh:
        page = json.load(fh)

    if "listingDetails" in page and "productsAnalytics" in page:
        fixture = modivo_fixture(page, args.items)
        _write(args.out, fixture)
        print(f"Wrote {len(fixture['products'])} items to {args.out}")
        return

    if "cards" in page and "summary" in page:
        fixture = saks85_fixture(page, args.items)
        _write(args.out, fixture)
        print(f"Wrote {len(fixture['cards'])} items to {args.out}")
        return

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
