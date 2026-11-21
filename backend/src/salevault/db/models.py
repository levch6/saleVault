"""SQLAlchemy models; see docs/reference/data-model.md. Money is integer minor units (kopecks)."""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from salevault.db.types import UtcDateTime, utcnow

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

RUN_STATUSES = ("running", "success", "partial", "failed", "cancelled")
RUN_TRIGGERS = ("cli", "ui")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UtcDateTime()}


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint(f"trigger IN {RUN_TRIGGERS}", name="trigger"),
        Index(None, "site_id", "status", "finished_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    status: Mapped[str] = mapped_column(String(16), default="running")
    trigger: Mapped[str] = mapped_column(String(8))
    pid: Mapped[int | None]
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    """Heartbeat, bumped on every progress update."""
    finished_at: Mapped[datetime | None]
    expected_total: Mapped[int | None]
    pages_total: Mapped[int | None]
    pages_done: Mapped[int] = mapped_column(default=0)
    items_seen: Mapped[int] = mapped_column(default=0)
    segments_json: Mapped[str | None] = mapped_column(Text)
    """Segment plan: [{sex, price, count, pages, full_pages, truncated}]."""
    category_tree_json: Mapped[str | None] = mapped_column(Text)
    """The shop's category tree as fetched by this run (CategoryNode list)."""
    stats_json: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class RunPage(Base):
    """Checkpoint: one fetched page of a segment, with the ids it contained."""

    __tablename__ = "run_pages"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), primary_key=True
    )
    segment_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    page: Mapped[int] = mapped_column(primary_key=True)
    items_count: Mapped[int]
    item_ids_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)


class RunItem(Base):
    """Staging: normalized items of a run, merged into products on finalization."""

    __tablename__ = "run_items"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    gender_mask: Mapped[int] = mapped_column(default=0)
    record_json: Mapped[str] = mapped_column(Text)


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("site_id", "external_id"), Index(None, "name"))

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(255))


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("site_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    depth: Mapped[int] = mapped_column(default=0)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("site_id", "external_id"),
        # Every sort and the cheap facets get an index led by `is_active`, so a page or a
        # GROUP BY walks the index instead of looking up 200k rows (see the bench script).
        Index(None, "is_active", "discount_pct", "savings_minor"),
        Index(None, "is_active", "discount_min30_pct", "discount_pct"),
        Index(None, "is_active", "savings_minor"),
        Index(None, "is_active", "price_minor"),
        Index(None, "is_active", "first_seen_at"),
        Index(None, "is_active", "brand_id"),
        Index(None, "is_active", "gender_mask"),
        Index(None, "site_id", "is_active", "discount_pct"),
        Index(None, "brand_id"),
        Index(None, "first_seen_run_id"),
        Index(None, "last_price_change_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    external_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(1024))
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(512))
    subtitle: Mapped[str | None] = mapped_column(String(512))
    color: Mapped[str | None] = mapped_column(String(128))
    gender_mask: Mapped[int] = mapped_column(default=0)
    image_name: Mapped[str | None] = mapped_column(String(255))
    image_version: Mapped[str | None] = mapped_column(String(64))
    gallery_json: Mapped[str] = mapped_column(Text, default="[]")

    price_minor: Mapped[int]
    price_regular_minor: Mapped[int]
    price_min30_minor: Mapped[int | None]
    discount_pct: Mapped[int]
    discount_min30_pct: Mapped[int | None]
    savings_minor: Mapped[int]
    prev_price_minor: Mapped[int | None]
    last_price_change_run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id"))

    is_active: Mapped[bool] = mapped_column(default=True)
    missed_runs: Mapped[int] = mapped_column(default=0)
    available_for_buy: Mapped[bool] = mapped_column(default=True)
    first_seen_at: Mapped[datetime]
    first_seen_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"))
    last_seen_at: Mapped[datetime]
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"))
    search_text: Mapped[str] = mapped_column(Text)


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (Index(None, "category_id"),)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )


class ProductSize(Base):
    __tablename__ = "product_sizes"
    # Covers both the size filter (EXISTS by product) and the size facet join.
    __table_args__ = (Index(None, "product_id", "in_stock", "label"),)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    variation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_external_id: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(64))
    ean: Mapped[str | None] = mapped_column(String(32))
    availability: Mapped[str] = mapped_column(String(32))
    in_stock: Mapped[bool]


class PriceHistory(Base):
    """Change log: a row when an item first appears or any of its prices changes."""

    __tablename__ = "price_history"
    __table_args__ = (Index(None, "product_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"))
    observed_at: Mapped[datetime]
    price_minor: Mapped[int]
    price_regular_minor: Mapped[int]
    price_min30_minor: Mapped[int | None]
    discount_pct: Mapped[int]


class Favorite(Base):
    __tablename__ = "favorites"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(default=utcnow)
    price_at_add_minor: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)


__all__ = [
    "RUN_STATUSES",
    "Base",
    "Brand",
    "Category",
    "Favorite",
    "PriceHistory",
    "Product",
    "ProductCategory",
    "ProductSize",
    "RunItem",
    "RunPage",
    "ScrapeRun",
    "Setting",
    "Site",
]
