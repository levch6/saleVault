"""Catalog queries for the HTTP API (read side). All functions take an open session."""

import json
from collections import OrderedDict, defaultdict
from collections.abc import Iterable, Sequence
from threading import Lock
from typing import Any

from sqlalchemy import and_, case, distinct, func, literal_column, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from salevault.catalog.filters import (
    CatalogFilter,
    RunContext,
    is_new,
    is_price_drop,
    load_run_context,
)
from salevault.catalog.schemas import (
    GENDER_BITS,
    GENDER_LABELS,
    Badge,
    BrandFacet,
    BrandOut,
    CatalogQuery,
    CategoryFacet,
    CategoryOut,
    Facets,
    FacetsQuery,
    FavoriteOut,
    GenderCode,
    HistoryPoint,
    ImageOut,
    ProductCard,
    ProductDetail,
    ProductPage,
    ProductsQuery,
    Range,
    SettingsIn,
    SettingsOut,
    SizeDetail,
    SizeFacet,
    SizeOut,
    Sort,
    ValueCount,
)
from salevault.db.models import (
    Brand,
    Category,
    Favorite,
    PriceHistory,
    Product,
    ProductCategory,
    ProductSize,
    ScrapeRun,
    Setting,
    Site,
)
from salevault.db.types import utcnow
from salevault.scraper.sites.registry import image_urls

MY_SIZES_KEY = "my_sizes"

ORDER: dict[Sort, tuple[Any, ...]] = {
    "discount_desc": (Product.discount_pct.desc(), Product.savings_minor.desc()),
    "discount_min30_desc": (
        Product.discount_min30_pct.desc().nulls_last(),
        Product.discount_pct.desc(),
    ),
    "savings_desc": (Product.savings_minor.desc(),),
    "price_asc": (Product.price_minor.asc(),),
    "price_desc": (Product.price_minor.desc(),),
    "newest": (Product.first_seen_at.desc(),),
}

CardRow = tuple[Product, str, str, str]
"""(product, brand name, site code, currency)."""


def whole(minor: int) -> int:
    """Minor units to whole currency units, rounding half up."""
    return (minor + 50) // 100


def resolve_filter(session: Session, query: CatalogQuery) -> CatalogFilter:
    site_ids: Sequence[int] = ()
    if query.site:
        site_ids = session.scalars(select(Site.id).where(Site.code.in_(query.site))).all()
    return CatalogFilter(
        query=query,
        site_ids=tuple(site_ids),
        my_sizes=tuple(read_my_sizes(session)),
        runs=load_run_context(session),
    )


def _card_select() -> Any:
    return (
        select(Product, Brand.name, Site.code, Site.currency)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Site, Site.id == Product.site_id)
    )


def list_products(session: Session, query: ProductsQuery) -> ProductPage:
    flt = resolve_filter(session, query)
    conds = flt.conditions()
    total = session.scalar(select(func.count()).select_from(Product).where(*conds)) or 0
    # Deferred join: sort and page over narrow rows, then load full rows for the page only.
    # Sorting thousands of full rows (names, search text, gallery) costs 10x more at 200k items.
    page_ids = session.scalars(
        select(Product.id)
        .where(*conds)
        .order_by(*ORDER[query.sort], Product.id)
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    ).all()
    by_id: dict[int, CardRow] = {
        p.id: (p, b, s, c)
        for p, b, s, c in session.execute(_card_select().where(Product.id.in_(page_ids)))
    }
    rows = [by_id[pid] for pid in page_ids]
    return ProductPage(
        items=_cards(session, rows, flt.runs, flt.my_sizes),
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


class _FacetCache:
    """Facets only change when a run is finalized or favorites / my sizes change."""

    def __init__(self, size: int = 128) -> None:
        self._size = size
        self._data: OrderedDict[tuple[object, ...], Facets] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple[object, ...]) -> Facets | None:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.move_to_end(key)
            return value

    def put(self, key: tuple[object, ...], value: Facets) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


facet_cache = _FacetCache()


def data_version(session: Session) -> tuple[object, ...]:
    """Changes whenever anything that facets depend on changes."""
    last_run = session.scalar(
        select(func.max(ScrapeRun.id)).where(ScrapeRun.status.in_(("success", "partial")))
    )
    fav_count, fav_last = session.execute(
        select(func.count(), func.max(Favorite.added_at)).select_from(Favorite)
    ).one()
    sizes = session.scalar(select(Setting.value_json).where(Setting.key == MY_SIZES_KEY))
    return (last_run, fav_count, fav_last, sizes)


def facets(session: Session, query: FacetsQuery) -> Facets:
    bind = session.get_bind()
    database = str(bind.engine.url)
    key = (database, query.model_dump_json(), *data_version(session))
    cached = facet_cache.get(key)
    if cached is not None:
        return cached
    result = _compute_facets(session, query)
    facet_cache.put(key, result)
    return result


def _pairs(session: Session, stmt: Any) -> dict[int, int]:
    return {key: count for key, count in session.execute(stmt)}  # noqa: C416 (Result has .keys())


def _compute_facets(session: Session, query: FacetsQuery) -> Facets:
    flt = resolve_filter(session, query)
    total = session.scalar(select(func.count()).select_from(Product).where(*flt.conditions())) or 0

    sites = [
        ValueCount(value=code, label=name, count=n)
        for code, name, n in session.execute(
            select(Site.code, Site.name, func.count(Product.id))
            .join(Site, Site.id == Product.site_id)
            .where(*flt.conditions(skip="site"))
            .group_by(Site.id)
            .order_by(Site.name)
        )
    ]

    gender_codes: list[GenderCode] = list(GENDER_BITS)
    gender_row = session.execute(
        select(
            *[
                func.coalesce(
                    func.sum(case((Product.gender_mask.op("&")(GENDER_BITS[g]) != 0, 1), else_=0)),
                    0,
                )
                for g in gender_codes
            ]
        ).where(*flt.conditions(skip="gender"))
    ).one()
    genders = [
        ValueCount(value=g, label=GENDER_LABELS[g], count=int(n))
        for g, n in zip(gender_codes, gender_row, strict=True)
    ]

    brand_counts = _pairs(
        session,
        select(Product.brand_id, func.count())
        .where(*flt.conditions(skip="brand"))
        .group_by(Product.brand_id),
    )
    brands = sorted(
        (
            BrandFacet(id=brand_id, name=name, count=brand_counts[brand_id])
            for brand_id, name in session.execute(
                select(Brand.id, Brand.name).where(Brand.id.in_(brand_counts))
            )
        ),
        key=lambda b: (-b.count, b.name),
    )

    categories: list[CategoryFacet] | None = None
    sizes: list[SizeFacet] | None = None
    if query.heavy:
        category_counts = _pairs(
            session,
            select(ProductCategory.category_id, func.count())
            .select_from(Product)
            .join(ProductCategory, ProductCategory.product_id == Product.id)
            .where(*flt.conditions(skip="category"))
            .group_by(ProductCategory.category_id),
        )
        categories = [
            CategoryFacet(
                id=cid, name=name, parent_id=parent, depth=depth, count=category_counts[cid]
            )
            for cid, name, parent, depth in session.execute(
                select(Category.id, Category.name, Category.parent_id, Category.depth)
                .where(Category.id.in_(category_counts))
                .order_by(Category.depth, Category.name)
            )
        ]

        sizes = [
            SizeFacet(label=label, count=n)
            for label, n in session.execute(
                select(ProductSize.label, func.count(distinct(ProductSize.product_id)).label("n"))
                .select_from(Product)
                .join(
                    ProductSize,
                    and_(ProductSize.product_id == Product.id, ProductSize.in_stock.is_(True)),
                )
                .where(*flt.conditions(skip="size"))
                .group_by(ProductSize.label)
                .order_by(literal_column("n").desc(), ProductSize.label)
            )
        ]

    price_min, price_max = session.execute(
        select(func.min(Product.price_minor), func.max(Product.price_minor)).where(
            *flt.conditions(skip="price")
        )
    ).one()
    disc_min, disc_max = session.execute(
        select(func.min(Product.discount_pct), func.max(Product.discount_pct)).where(
            *flt.conditions(skip="discount")
        )
    ).one()

    return Facets(
        total=total,
        sites=sites,
        genders=genders,
        categories=categories,
        brands=brands,
        sizes=sizes,
        price=Range(
            min=whole(price_min) if price_min is not None else None,
            max=whole(price_max) if price_max is not None else None,
        ),
        discount=Range(min=disc_min, max=disc_max),
    )


def product_detail(session: Session, product_id: int) -> ProductDetail | None:
    row = session.execute(_card_select().where(Product.id == product_id)).first()
    if row is None:
        return None
    product, brand_name, site_code, currency = row
    runs = load_run_context(session)
    mine = set(read_my_sizes(session))
    card = _cards(session, [(product, brand_name, site_code, currency)], runs, mine)[0]

    size_details = [
        SizeDetail(label=label, in_stock=in_stock, is_mine=label in mine, availability=avail)
        for label, in_stock, avail in session.execute(
            select(ProductSize.label, ProductSize.in_stock, ProductSize.availability)
            .where(ProductSize.product_id == product_id)
            .order_by(literal_column("rowid"))
        )
    ]
    category_paths = _category_paths(session, product_id)
    history = [
        HistoryPoint(
            observed_at=h.observed_at,
            price=whole(h.price_minor),
            price_regular=whole(h.price_regular_minor),
            price_min30=whole(h.price_min30_minor) if h.price_min30_minor is not None else None,
            discount_pct=h.discount_pct,
        )
        for h in session.scalars(
            select(PriceHistory)
            .where(PriceHistory.product_id == product_id)
            .order_by(PriceHistory.observed_at, PriceHistory.id)
        )
    ]
    gallery = [
        image
        for name, version in json.loads(product.gallery_json)
        if (image := _image(site_code, name, version)) is not None
    ]
    return ProductDetail(
        **card.model_dump(),
        gallery=gallery,
        category_paths=category_paths,
        size_details=size_details,
        price_history=history,
        last_seen_at=product.last_seen_at,
    )


def _category_paths(session: Session, product_id: int) -> list[list[CategoryOut]]:
    linked = {
        cid: (name, parent)
        for cid, name, parent in session.execute(
            select(Category.id, Category.name, Category.parent_id)
            .join(ProductCategory, ProductCategory.category_id == Category.id)
            .where(ProductCategory.product_id == product_id)
        )
    }
    parents = {parent for _name, parent in linked.values() if parent is not None}
    paths = []
    for leaf in (cid for cid in linked if cid not in parents):
        path: list[CategoryOut] = []
        current: int | None = leaf
        while current is not None and current in linked:
            name, parent = linked[current]
            path.append(CategoryOut(id=current, name=name))
            current = parent
        paths.append(path[::-1])
    return sorted(paths, key=lambda p: [c.name for c in p])


# --- favorites ---------------------------------------------------------------------------------


def list_favorites(session: Session) -> list[FavoriteOut]:
    favs = {f.product_id: f for f in session.scalars(select(Favorite))}
    if not favs:
        return []
    rows: list[CardRow] = [
        (p, b, s, c)
        for p, b, s, c in session.execute(
            _card_select().where(Product.id.in_(favs)).order_by(Product.discount_pct.desc())
        )
    ]
    cards = _cards(session, rows, load_run_context(session), read_my_sizes(session))
    out = []
    for (product, *_), card in zip(rows, cards, strict=True):
        fav = favs[product.id]
        out.append(
            FavoriteOut(
                product=card,
                added_at=fav.added_at,
                price_at_add=whole(fav.price_at_add_minor),
                price_change=whole(product.price_minor) - whole(fav.price_at_add_minor),
                note=fav.note,
            )
        )
    out.sort(key=lambda f: f.added_at, reverse=True)
    return out


def add_favorite(session: Session, product_id: int, note: str | None) -> bool:
    """Idempotent; returns False if the product does not exist."""
    product = session.get(Product, product_id)
    if product is None:
        return False
    favorite = session.get(Favorite, product_id)
    if favorite is None:
        session.add(
            Favorite(
                product_id=product_id,
                added_at=utcnow(),
                price_at_add_minor=product.price_minor,
                note=note,
            )
        )
    elif note is not None:
        favorite.note = note
    return True


def remove_favorite(session: Session, product_id: int) -> None:
    favorite = session.get(Favorite, product_id)
    if favorite is not None:
        session.delete(favorite)


# --- settings ----------------------------------------------------------------------------------


def read_my_sizes(session: Session) -> list[str]:
    raw = session.scalar(select(Setting.value_json).where(Setting.key == MY_SIZES_KEY))
    value = json.loads(raw) if raw else []
    return [str(v) for v in value] if isinstance(value, list) else []


def read_settings(session: Session) -> SettingsOut:
    return SettingsOut(my_sizes=read_my_sizes(session))


def update_settings(session: Session, data: SettingsIn) -> SettingsOut:
    if data.my_sizes is not None:
        sizes = list(dict.fromkeys(s.strip() for s in data.my_sizes if s.strip()))
        stmt = sqlite_insert(Setting).values(key=MY_SIZES_KEY, value_json=json.dumps(sizes))
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Setting.key], set_={"value_json": stmt.excluded.value_json}
            )
        )
    return read_settings(session)


# --- cards -------------------------------------------------------------------------------------


def _image(site_code: str, name: str | None, version: str | None) -> ImageOut | None:
    if not name or version is None:
        return None
    urls = image_urls(site_code, name, version)
    return ImageOut(thumb=urls[0], full=urls[1]) if urls else None


def _cards(
    session: Session, rows: Sequence[CardRow], runs: RunContext, my_sizes: Iterable[str]
) -> list[ProductCard]:
    ids = [p.id for p, *_ in rows]
    if not ids:
        return []
    mine = set(my_sizes)
    sizes: defaultdict[int, list[SizeOut]] = defaultdict(list)
    for product_id, label, in_stock in session.execute(
        select(ProductSize.product_id, ProductSize.label, ProductSize.in_stock)
        .where(ProductSize.product_id.in_(ids))
        .order_by(ProductSize.product_id, literal_column("rowid"))
    ):
        sizes[product_id].append(SizeOut(label=label, in_stock=in_stock, is_mine=label in mine))
    favorites = set(
        session.scalars(select(Favorite.product_id).where(Favorite.product_id.in_(ids)))
    )

    cards = []
    for p, brand_name, site_code, currency in rows:
        badges: list[Badge] = []
        if is_new(p.first_seen_run_id, p.site_id, runs):
            badges.append("new")
        if is_price_drop(
            p.last_price_change_run_id, p.price_minor, p.prev_price_minor, p.site_id, runs
        ):
            badges.append("price_drop")
        cards.append(
            ProductCard(
                id=p.id,
                site=site_code,
                url=p.url,
                brand=BrandOut(id=p.brand_id, name=brand_name),
                name=p.name,
                subtitle=p.subtitle,
                color=p.color,
                image=_image(site_code, p.image_name, p.image_version),
                price=whole(p.price_minor),
                price_regular=whole(p.price_regular_minor),
                price_min30=whole(p.price_min30_minor) if p.price_min30_minor is not None else None,
                currency=currency,
                discount_pct=p.discount_pct,
                discount_min30_pct=p.discount_min30_pct,
                savings=whole(p.savings_minor),
                prev_price=whole(p.prev_price_minor) if p.prev_price_minor is not None else None,
                badges=badges,
                genders=[g for g, bit in GENDER_BITS.items() if p.gender_mask & bit],
                sizes=sizes[p.id],
                is_favorite=p.id in favorites,
                is_active=p.is_active,
                first_seen_at=p.first_seen_at,
            )
        )
    return cards
