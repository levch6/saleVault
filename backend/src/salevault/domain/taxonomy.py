# Matching shop vocabulary needs Cyrillic letters that look like Latin ones.
# ruff: noqa: RUF001, RUF002
"""The app's own category tree, shared by every shop, and the rules that place a product in it.

Shops name and nest their categories differently (some start with the gender, some are flat,
some have none), so the catalog filter does not use them. Every product gets one category of
this tree instead, from the evidence its shop gives: the shop's category path, most specific
first, then the product's name and subtitle. Gender is not part of the tree; it is a filter of
its own. See docs/decisions/0009-shared-category-tree.md.
"""

import functools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

TAXONOMY_VERSION = 1
"""Bump on any change of the tree or the rules: products are categorized again on start."""


@dataclass(frozen=True, slots=True)
class Node:
    slug: str
    """Stable id: `group` or `group.leaf`. Used in URLs, so never reuse a removed one."""
    name: str

    @property
    def parent(self) -> str | None:
        group, dot, _ = self.slug.partition(".")
        return group if dot else None


def _group(slug: str, name: str, *leaves: tuple[str, str]) -> list[Node]:
    return [Node(slug, name), *(Node(f"{slug}.{leaf}", leaf_name) for leaf, leaf_name in leaves)]


TREE: tuple[Node, ...] = (
    *_group(
        "clothing",
        "Clothing",
        ("tshirts", "T-shirts and tops"),
        ("polos", "Polo shirts"),
        ("shirts", "Shirts and blouses"),
        ("sweaters", "Sweaters and cardigans"),
        ("hoodies", "Hoodies and sweatshirts"),
        ("jackets", "Jackets"),
        ("coats", "Coats"),
        ("vests", "Vests"),
        ("blazers", "Blazers and suits"),
        ("dresses", "Dresses"),
        ("skirts", "Skirts"),
        ("trousers", "Trousers"),
        ("jeans", "Jeans"),
        ("sweatpants", "Sweatpants"),
        ("leggings", "Leggings"),
        ("shorts", "Shorts"),
        ("jumpsuits", "Jumpsuits"),
        ("tracksuits", "Tracksuits"),
        ("swimwear", "Swimwear"),
        ("underwear", "Underwear"),
        ("socks", "Socks and tights"),
        ("sleepwear", "Sleepwear"),
        ("other", "Other clothing"),
    ),
    *_group(
        "shoes",
        "Shoes",
        ("sneakers", "Sneakers"),
        ("boots", "Boots"),
        ("flats", "Shoes and loafers"),
        ("heels", "Heels"),
        ("sandals", "Sandals"),
        ("slides", "Slides and slippers"),
        ("other", "Other shoes"),
    ),
    *_group(
        "bags",
        "Bags",
        ("handbags", "Handbags"),
        ("backpacks", "Backpacks"),
        ("beltbags", "Belt bags"),
        ("travel", "Travel and sports bags"),
        ("wallets", "Wallets and cardholders"),
        ("other", "Other bags"),
    ),
    *_group(
        "accessories",
        "Accessories",
        ("hats", "Caps and hats"),
        ("scarves", "Scarves"),
        ("gloves", "Gloves"),
        ("belts", "Belts"),
        ("sunglasses", "Sunglasses"),
        ("jewelry", "Jewelry"),
        ("watches", "Watches"),
        ("other", "Other accessories"),
    ),
    *_group(
        "home",
        "Home",
        ("textiles", "Home textiles"),
        ("kitchen", "Kitchen and tableware"),
        ("decor", "Decor and lighting"),
        ("fragrance", "Candles and home fragrance"),
        ("other", "Other home"),
    ),
    *_group(
        "lifestyle",
        "Lifestyle",
        ("beauty", "Beauty and perfume"),
        ("sport", "Sport and outdoor gear"),
        ("tech", "Tech and gadgets"),
        ("books", "Books and games"),
        ("other", "Other lifestyle"),
    ),
    Node("other", "Other"),
)

NODES: dict[str, Node] = {node.slug: node for node in TREE}
OTHER = "other"


# --- Rules -------------------------------------------------------------------------------------
#
# Each rule is a leaf and a regular expression over normalized text (casefolded, look-alike
# Latin letters inside Cyrillic words replaced, apostrophes unified). Rules are tried in order,
# so a more specific one comes first: "джинсова куртка" is a jacket, not jeans; "сукня-сорочка"
# is a dress, not a shirt. Stems start at a word boundary. Ukrainian first, then the Czech and
# English words that shops leave untranslated.


def _words(*stems: str) -> str:
    return r"\b(?:" + "|".join(stems) + r")"


_RULES: tuple[tuple[str, str], ...] = (
    # Things that are not what their words suggest.
    ("shoes.other", _words(r"догляд за взуттям", r"шнурк", r"устілк", r"пінетк", r"shoe care")),
    ("bags.other", _words(r"косметичк", r"несесер")),
    ("bags.wallets", _words(r"для кредиток", r"банківськ", r"для карт")),
    ("lifestyle.other", _words(r"для собак", r"для кот", r"улюбленц")),
    ("home.textiles", _words(r"чохл\w* для подуш")),
    (
        "clothing.swimwear",
        _words(r"купальн", r"для плаванн", r"плавк", r"пляжн", r"бікіні", r"swim", r"plavk"),
    ),
    ("clothing.sleepwear", _words(r"піжам", r"нічн\w* сорочк", r"халат", r"pyžam", r"pyjam")),
    ("clothing.tracksuits", _words(r"спортивн\w* костюм", r"tracksuit", r"souprav")),
    ("clothing.trousers", _words(r"костюмн\w* штан", r"штани та легінси")),
    ("clothing.tshirts", _words(r"футболки (?:та|і) поло", r"футболки (?:та|і) майки")),
    ("clothing.hoodies", _words(r"sweat ?shirt", r"hooded", r"track jacket", r"track top")),
    (
        "clothing.sweatpants",
        _words(r"спортивн\w* штан", r"джогер", r"jogger", r"sweatpant", r"tepl"),
    ),
    ("clothing.leggings", _words(r"легінс", r"лосин", r"legín", r"legging")),
    # Shoes before clothing: "черевики" are never trousers.
    ("shoes.heels", _words(r"на підбор", r"на шпильц", r"човник", r"heel", r"pump")),
    ("shoes.sandals", _words(r"сандал", r"босоніж", r"sandal", r"sandál")),
    (
        "shoes.slides",
        _words(
            r"шльопан",
            r"в'єтнам",
            r"тапоч",
            r"тапк",
            r"капц",
            r"slide",
            r"slipper",
            r"flip",
            r"pantof",
        ),
    ),
    (
        "shoes.boots",
        _words(
            r"черевик",
            r"чобот",
            r"ботильйон",
            r"челсі",
            r"снігоход",
            r"дутик",
            r"угг",
            r"берц",
            r"ботфорт",
            r"зимове\b",
            r"boot",
            r"chelsea",
        ),
    ),
    (
        "shoes.sneakers",
        _words(
            r"кросів", r"кед", r"снікер", r"сникер", r"sneaker", r"trainer", r"tenisk", r"slip-?on"
        ),
    ),
    (
        "shoes.flats",
        _words(
            r"туфл",
            r"туфел",
            r"лофер",
            r"мокасин",
            r"балетк",
            r"еспадрил",
            r"сліпер",
            r"сліпон",
            r"броги",
            r"оксфорд",
            r"дербі",
            r"мюлі",
            r"сабо",
            r"loafer",
            r"mokasín",
            r"mule",
            r"clog",
            r"ballet",
        ),
    ),
    # Bags and small leather goods.
    (
        "bags.wallets",
        _words(
            r"гаман", r"портмоне", r"картхолдер", r"кардхолдер", r"візитниц", r"wallet", r"peněženk"
        ),
    ),
    (
        "bags.beltbags",
        _words(r"на пояс", r"поясн\w* сум", r"барсет", r"бананк", r"belt bag", r"ledvink"),
    ),
    ("bags.backpacks", _words(r"рюкзак", r"backpack", r"batoh")),
    (
        "bags.travel",
        _words(r"валіз", r"дорожн\w* сум", r"спортивн\w* сум", r"сумки та валізи", r"duffle"),
    ),
    (
        "bags.handbags",
        _words(
            r"сум(?:к|ок|оч)",
            r"клатч",
            r"crossbody",
            r"через плече",
            r"shopper",
            r"tote",
            r"kabelk",
            r"bag",
        ),
    ),
    # Accessories.
    (
        "accessories.hats",
        _words(
            r"кепк",
            r"кепок",
            r"кепі",
            r"бейсболк",
            r"шап(?:к|ок)",
            r"капелюх",
            r"панам",
            r"берет",
            r"балаклав",
            r"головн\w* убор",
            r"cap\b",
            r"hat\b",
            r"beanie",
            r"čepic",
            r"kšilt",
        ),
    ),
    (
        "accessories.scarves",
        _words(r"шарф", r"шал[ьі]", r"хустк", r"хусток", r"снуд", r"палантин", r"scarf", r"šál"),
    ),
    ("accessories.gloves", _words(r"рукавиц", r"рукавич", r"gloves?", r"rukavic")),
    ("accessories.belts", _words(r"ремін", r"ремен", r"ремні", r"пасок", r"belt\b", r"pásk")),
    ("accessories.sunglasses", _words(r"окуляр", r"sunglass", r"brýle")),
    ("accessories.watches", _words(r"годинник", r"watch", r"hodink")),
    (
        "accessories.jewelry",
        _words(
            r"біжутер",
            r"ювелір",
            r"прикрас",
            r"сереж",
            r"кільц",
            r"каблуч",
            r"перстен",
            r"персн",
            r"ланцюж",
            r"браслет",
            r"кулон",
            r"намист",
            r"підвіс",
            r"брош",
            r"кольє",
            r"prsten",
            r"náramk",
            r"náušnic",
            r"řetíz",
            r"jewel",
        ),
    ),
    # Clothing, specific before general ("t-shirt" before "shirt").
    ("clothing.tshirts", _words(r"t-shirt", r"tee\b", r"tričk", r"longsleeve", r"боді", r"body")),
    ("clothing.dresses", _words(r"сукн", r"суконь", r"плаття", r"сарафан", r"dress", r"šat")),
    ("clothing.skirts", _words(r"спідниц", r"skirt", r"sukn")),
    (
        "clothing.jumpsuits",
        _words(r"комбінезон", r"чоловічок", r"overall", r"overaly", r"jumpsuit"),
    ),
    ("clothing.shorts", _words(r"шорт", r"бермуд", r"short", r"kraťas")),
    (
        "clothing.coats",
        _words(
            r"пальт", r"тренч", r"плащ", r"шуб", r"дублянк", r"тулуб", r"овчин", r"coat", r"kabát"
        ),
    ),
    ("clothing.vests", _words(r"жилет", r"безрукав", r"vest\b", r"gilet", r"vesty")),
    (
        "clothing.jackets",
        _words(
            r"курт(?:к|ок)",
            r"пуховик",
            r"бомбер",
            r"вітрівк",
            r"вітровк",
            r"дощовик",
            r"анорак",
            r"парк[аи]\b",
            r"jacket",
            r"bunda",
            r"bundy",
            r"péřov",
            r"parka",
            r"větrovk",
        ),
    ),
    (
        "clothing.blazers",
        _words(r"піджак", r"жакет", r"костюм", r"смокінг", r"blazer", r"sak[oa]\b"),
    ),
    ("clothing.polos", _words(r"поло\b", r"polo\b")),
    ("clothing.shirts", _words(r"сороч", r"блуз", r"shirt\b", r"košil", r"halenk")),
    (
        "clothing.hoodies",
        _words(
            r"худі",
            r"світшот",
            r"кофт",
            r"реглан",
            r"толстовк",
            r"фліс",
            r"hoodie",
            r"sweatshirt",
            r"mikin",
        ),
    ),
    (
        "clothing.sweaters",
        _words(
            r"светр",
            r"кардиган",
            r"джемпер",
            r"пуловер",
            r"болеро",
            r"гольф\b",
            r"водолазк",
            r"трикотаж",
            r"sweater",
            r"cardigan",
            r"svetr",
        ),
    ),
    ("clothing.jeans", _words(r"джинс", r"jeans", r"džín")),
    (
        "clothing.trousers",
        _words(
            r"штан",
            r"брюк",
            r"кюлот",
            r"чінос",
            r"карго",
            r"trouser",
            r"pants",
            r"kalhot\b",
            r"kalhoty",
        ),
    ),
    (
        "clothing.underwear",
        _words(
            r"білизн",
            r"трус",
            r"боксер",
            r"сліп",
            r"слип",
            r"стрінг",
            r"бюстг",
            r"бралет",
            r"бра\b",
            r"трунк",
            r"boxer",
            r"slip",
            r"kalhotk",
            r"podprsenk",
        ),
    ),
    (
        "clothing.socks",
        _words(r"шкарпет", r"колгот", r"гольфи", r"панчох", r"панчіх", r"socks?", r"ponožk"),
    ),
    (
        "clothing.tshirts",
        _words(
            r"футбол(?:к|ок)",
            r"майк",
            r"майок",
            r"лонгслів",
            r"топ",
            r"кроп",
            r"джерсі",
            r"jersey",
            r"tíl",
            r"top\b",
            r"tank",
        ),
    ),
    # Home and lifestyle.
    ("lifestyle.books", _words(r"книг", r"bookstore", r"альбом", r"ігри", r"пазл")),
    ("home.fragrance", _words(r"свіч(?:к|ок)", r"аромат", r"дифузор", r"candle")),
    (
        "home.textiles",
        _words(
            r"подуш", r"ковдр", r"плед", r"рушник", r"постільн", r"килим", r"текстиль", r"towel"
        ),
    ),
    (
        "home.kitchen",
        _words(
            r"кухн",
            r"посуд",
            r"чаш(?:к|ок)",
            r"круж",
            r"тарілк",
            r"склян",
            r"миск",
            r"келих",
            r"графин",
            r"глечик",
            r"прибор",
            r"сервір",
            r"кав",
            r"чай",
            r"mug",
        ),
    ),
    (
        "home.decor",
        _words(
            r"декор",
            r"ваз",
            r"підсвічник",
            r"ламп",
            r"освітлен",
            r"фігурк",
            r"рамк",
            r"дзеркал",
            r"картин",
            r"постер",
            r"горщик",
            r"кошик",
            r"органайзер",
        ),
    ),
    (
        "lifestyle.beauty",
        _words(
            r"парфум",
            r"туалетн\w* вод",
            r"косметичн\w* засоб",
            r"spa",
            r"wellness",
            r"perfume",
            r"parfém",
        ),
    ),
    (
        "lifestyle.sport",
        _words(
            r"спортивн\w* обладнан",
            r"туризм",
            r"свіжому повітрі",
            r"пляш",
            r"термос",
            r"термочаш",
            r"термопляш",
            r"ракетк",
            r"м'яч",
            r"bottle",
        ),
    ),
    (
        "lifestyle.tech",
        _words(r"ґаджет", r"гаджет", r"навушник", r"колонк", r"ноутбук", r"телефон", r"техн"),
    ),
    ("home.other", _words(r"для ванн", r"меблі", r"столик", r"зберіган")),
    # Small accessories last: "чохол для подушки" is home textile, "чохол для карток" a wallet.
    (
        "accessories.other",
        _words(
            r"чохл", r"чохол", r"брелок", r"брелк", r"значк", r"парасол", r"краватк", r"метелик"
        ),
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (leaf, re.compile(pattern)) for leaf, pattern in _RULES
)

_GROUP_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (leaf, re.compile(_words(*stems)))
    for leaf, stems in (
        # A shop that only says "shoes" sells sneakers in practice: Footshop's general men's
        # and women's shoe categories were 94% sneakers (2026-11-21); explicit boots, slides
        # and the like are caught by the rules above, through the product name.
        ("shoes.sneakers", (r"взутт", r"обув", r"footwear", r"shoes?", r"boty")),
        ("clothing.other", (r"одяг", r"clothing", r"apparel", r"oblečen", r"комплект", r"мода")),
        ("accessories.other", (r"аксесуар", r"accessor", r"doplňk")),
        ("home.other", (r"дім", r"для дому", r"вітальн", r"спальн", r"ванн", r"home")),
        ("lifestyle.other", (r"лайфстайл", r"lifestyle", r"подарун", r"культур")),
    )
)

_LATIN_LOOKALIKES = str.maketrans("aceiopxykmht", "асеіорхукмнт")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'"})


def normalize(text: str) -> str:
    """Casefolded text with look-alike Latin letters inside Cyrillic words made Cyrillic (shops
    type "Снікерcи" with a Latin "c") and every apostrophe written as `'`."""
    words = []
    for word in text.casefold().translate(_APOSTROPHES).split():
        if _CYRILLIC.search(word):
            word = word.translate(_LATIN_LOOKALIKES)
        words.append(word)
    return " ".join(words)


def categorize(path: Sequence[str], names: Sequence[str | None], brand: str | None = None) -> str:
    """The leaf for a product.

    `path` is the shop's category path from the deepest category up (empty when the shop has
    none); `names` are the product's name and subtitle; `brand` is removed from them, so a
    brand like "Polo Ralph Lauren" does not make everything a polo shirt.

    1. A deepest category that names a kind of product decides (shops know their items).
    2. Otherwise the deepest category is a style ("Без застібки", "Довгий рукав") and its
       parents name the kind. The product name may refine it within the same group of
       clothing, shoes, bags or accessories ("Штани та легінси" + "Штани" is trousers).
    3. Without any kind in the path, the name decides (shops with flat or no categories).
    4. Then the first general hint ("shoes", "clothing", "home"...) gives a group's catch-all.
    """
    texts = [normalize(text) for text in path if text and text.strip()]
    bare = [normalize(_without(name, brand)) for name in names if name and name.strip()]
    if texts and (leaf := _first_rule(texts[:1])):
        return leaf
    # A style is read together with its parent: "спортивні" under "штани" is sweatpants.
    from_path = _first_rule([" ".join(texts[:2]), *texts[1:]] if len(texts) > 1 else [])
    from_name = _first_rule(bare)
    if from_path and from_name and _group_of(from_path) == _group_of(from_name) in _REFINABLE:
        return from_name
    if from_path or from_name:
        return from_path or from_name or OTHER
    for text in [*texts, *bare]:
        for leaf, pattern in _GROUP_HINTS:
            if pattern.search(text):
                return leaf
    return OTHER


_REFINABLE = frozenset({"clothing", "shoes", "bags", "accessories"})


def _first_rule(texts: Iterable[str]) -> str | None:
    for text in texts:
        if leaf := _rule_for(text):
            return leaf
    return None


@functools.lru_cache(maxsize=65_536)
def _rule_for(text: str) -> str | None:
    """Category names and kinds repeat across thousands of items, so their answer is cached."""
    for leaf, pattern in _COMPILED:
        if pattern.search(text):
            return leaf
    return None


def _group_of(slug: str) -> str:
    return slug.partition(".")[0]


def _without(name: str, brand: str | None) -> str:
    if not brand or not brand.strip():
        return name
    return re.sub(re.escape(brand.strip()), " ", name, flags=re.IGNORECASE)


def ancestors(slug: str) -> list[str]:
    """The slug and its group, most general first: `["clothing", "clothing.jackets"]`."""
    node = NODES.get(slug)
    if node is None:
        return []
    return [node.parent, slug] if node.parent else [slug]


def leaves_of(slugs: Sequence[str]) -> list[str]:
    """Every leaf the given nodes stand for (a group stands for all of its leaves)."""
    wanted = set(slugs)
    return [
        node.slug
        for node in TREE
        if node.slug in wanted or (node.parent is not None and node.parent in wanted)
    ]
