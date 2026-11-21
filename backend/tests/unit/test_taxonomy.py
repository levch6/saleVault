# Shop vocabulary in Cyrillic, including letters that look like Latin ones.
# ruff: noqa: RUF001
import pytest

from salevault.domain.taxonomy import (
    _RULES,
    NODES,
    OTHER,
    TREE,
    ancestors,
    categorize,
    leaves_of,
    normalize,
)


def test_the_tree_is_two_levels_with_known_parents() -> None:
    slugs = [node.slug for node in TREE]
    assert len(slugs) == len(set(slugs))
    for node in TREE:
        assert node.parent is None or node.parent in NODES
        assert node.slug.count(".") <= 1
    assert all(f"{group}.other" in NODES for group in ("clothing", "shoes", "bags", "home"))


def test_every_rule_points_to_a_leaf() -> None:
    for leaf, _pattern in _RULES:
        assert leaf in NODES, leaf
        assert NODES[leaf].parent is not None, f"{leaf} is a group"


def test_normalize_fixes_look_alike_latin_letters_and_apostrophes() -> None:
    assert normalize("Снікерcи") == "снікерси"  # a Latin "c"
    assert normalize("Cпідниця-міні") == "спідниця-міні"
    assert normalize("В’єтнамки") == "в'єтнамки"
    assert normalize("Air Max 90") == "air max 90"  # Latin words stay Latin


@pytest.mark.parametrize(
    ("path", "name", "expected"),
    [
        # A deepest category that names a kind decides.
        (["Кросівки лайфстайл", "Взуття", "Вона"], "Кросівки adidas", "shoes.sneakers"),
        (["Поло", "Футболки та поло", "Він"], "Поло", "clothing.polos"),
        (["Шльопанці", "Шльопанці і сандалі"], "", "shoes.slides"),
        (["Боксерки"], "", "clothing.underwear"),
        (["Boxerky"], "", "clothing.underwear"),
        (["Péřovky"], "", "clothing.jackets"),
        (["Kabelky"], "", "bags.handbags"),
        # A style is read with its parent.
        (["Спортивні", "Штани", "Він"], "", "clothing.sweatpants"),
        (["Без застібки", "Кофти", "Він"], "", "clothing.hoodies"),
        (["Relaxed", "Джинси", "Вона"], "", "clothing.jeans"),
        # The name refines a style within the same group...
        (["Довгий рукав", "Футболки та поло", "Він"], "Бавовняний лонгслів", "clothing.tshirts"),
        (["Без застібки", "Светри та кардигани"], "Вовняний жилет", "clothing.vests"),
        (["Із двох частин", "Купальники"], "трусики для плавання", "clothing.swimwear"),
        # ...but never across groups.
        (["Розкльошені", "Джинси"], "джинси bootcut", "clothing.jeans"),
        (["Пов'язки", "Головні убори"], "Навушники дитячі", "accessories.hats"),
        # No kind in the path: the name decides.
        (["Чоловіче взуття"], "Sinclair Jungle Boot", "shoes.boots"),
        (["Взуття"], "Жіночі черевики", "shoes.boots"),
        ([], "Туфлі на шпильці", "shoes.heels"),
        ([], "Джинсова куртка", "clothing.jackets"),
        ([], "Сукня-сорочка", "clothing.dresses"),
        ([], "Джинсові шорти", "clothing.shorts"),
        ([], "Спортивний костюм", "clothing.tracksuits"),
        ([], "Комплект футболок", "clothing.tshirts"),
        ([], "Гольф", "clothing.sweaters"),
        ([], "Гольфи", "clothing.socks"),
        ([], "Classic Slip-On", "shoes.sneakers"),
        ([], "Organic cotton T-shirt", "clothing.tshirts"),
        ([], "Чохол для кредиток", "bags.wallets"),
        (["Подушки", "Вітальня та спальня"], "Чохол для подушки", "home.textiles"),
        # Only a general hint: the group's catch-all, sneakers for plain "shoes".
        (["Чоловіче взуття"], "Air Max 90", "shoes.sneakers"),
        (["Комплекти", "Одяг", "Діти"], "Комплект", "clothing.other"),
        (["Аксесуари"], "Брелок", "accessories.other"),
        # Nothing at all.
        ([], "", OTHER),
        (["Набори"], "Набір дитячий", OTHER),
    ],
)
def test_categorize(path: list[str], name: str, expected: str) -> None:
    assert categorize(path, [name]) == expected


def test_the_brand_does_not_count() -> None:
    path = ["З текстилю", "Штани"]

    assert categorize(path, ["Polo Ralph Lauren штани"], "Polo Ralph Lauren") == "clothing.trousers"
    assert categorize([], ["Polo Ralph Lauren"], "Polo Ralph Lauren") == OTHER


def test_the_subtitle_is_evidence_too() -> None:
    assert categorize([], ["Product 1", "зимова куртка"]) == "clothing.jackets"


def test_ancestors_and_leaves() -> None:
    assert ancestors("clothing.jackets") == ["clothing", "clothing.jackets"]
    assert ancestors("other") == ["other"]
    assert ancestors("nope") == []
    assert "clothing.jackets" in leaves_of(["clothing"])
    assert leaves_of(["shoes.boots", "other"]) == ["shoes.boots", "other"]
