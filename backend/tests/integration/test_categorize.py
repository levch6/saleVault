import json

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from salevault.db.categorize import (
    TAXONOMY_KEY,
    Coverage,
    coverage,
    ensure_categorized,
    path_names,
    recategorize,
    recompute_depths,
)
from salevault.db.engine import session_scope
from salevault.db.models import Category, Product, Setting, Site
from salevault.domain.models import Gender
from salevault.domain.taxonomy import TAXONOMY_VERSION
from tests.fakes import FAKE_SITE
from tests.integration.helpers import product, seed_run

JACKETS = [("1", "Одяг"), ("2", "Куртки")]
STYLE = [("1", "Одяг"), ("3", "Без застібки")]


def slugs(factory: sessionmaker[Session]) -> dict[str, str]:
    with session_scope(factory) as session:
        return {  # noqa: C416 (dict(Result) breaks: Result has .keys())
            ext: slug
            for ext, slug in session.execute(select(Product.external_id, Product.category_slug))
        }


def test_a_merge_stores_the_shared_category(factory: sessionmaker[Session]) -> None:
    seed_run(
        factory,
        FAKE_SITE,
        [
            (
                Gender.MEN,
                [
                    product("a", 100, regular=200, categories=JACKETS),
                    product("b", 100, regular=200, categories=STYLE),
                    product("c", 100, regular=200, categories=[]),
                ],
            )
        ],
    )

    assert slugs(factory) == {"a": "clothing.jackets", "b": "clothing.other", "c": "other"}


def test_recategorize_follows_rule_changes(factory: sessionmaker[Session]) -> None:
    seed_run(
        factory, FAKE_SITE, [(Gender.MEN, [product("a", 100, regular=200, categories=JACKETS)])]
    )
    with session_scope(factory) as session:
        session.execute(update(Product).values(category_slug="other"))

    with session_scope(factory) as session:
        assert recategorize(session) == 1
        assert recategorize(session) == 0

    assert slugs(factory) == {"a": "clothing.jackets"}


def test_the_catalog_is_categorized_once_per_rules_version(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    seed_run(
        factory, FAKE_SITE, [(Gender.MEN, [product("a", 100, regular=200, categories=JACKETS)])]
    )
    with session_scope(factory) as session:
        stored = session.scalar(select(Setting.value_json).where(Setting.key == TAXONOMY_KEY))
        assert stored is not None
        assert json.loads(stored)["version"] == TAXONOMY_VERSION
        session.execute(update(Product).values(category_slug="other"))

    ensure_categorized(engine)  # same version: nothing to do
    assert slugs(factory) == {"a": "other"}

    with session_scope(factory) as session:
        session.execute(
            update(Setting).where(Setting.key == TAXONOMY_KEY).values(value_json='{"version": 0}')
        )
    ensure_categorized(engine)
    assert slugs(factory) == {"a": "clothing.jackets"}


def test_depths_follow_the_parent_links(factory: sessionmaker[Session]) -> None:
    seed_run(
        factory, FAKE_SITE, [(Gender.MEN, [product("a", 100, regular=200, categories=JACKETS)])]
    )
    with session_scope(factory) as session:
        site_id = session.scalar(select(Site.id))
        assert site_id is not None
        session.execute(update(Category).where(Category.external_id == "2").values(depth=11))
        recompute_depths(session, site_id)
    with session_scope(factory) as session:
        depths = {  # noqa: C416 (dict(Result) breaks: Result has .keys())
            ext: depth
            for ext, depth in session.execute(select(Category.external_id, Category.depth))
        }
    assert depths == {"1": 0, "2": 1}


def test_path_names_put_the_deepest_category_first() -> None:
    parents = {"root": None, "mid": "root", "leaf": "mid", "other": None, "o2": "other"}
    names = {"root": "Root", "mid": "Mid", "leaf": "Leaf", "other": "Other", "o2": "O2"}

    assert path_names(["leaf"], parents, names) == ["Leaf", "Mid", "Root"]
    # Glued paths: the deepest chain first, so a style's parent is its own parent.
    assert path_names(["o2", "leaf"], parents, names) == ["Leaf", "Mid", "Root", "O2", "Other"]


def test_coverage_report(factory: sessionmaker[Session]) -> None:
    seed_run(
        factory,
        FAKE_SITE,
        [
            (
                Gender.MEN,
                [
                    product("a", 100, regular=200, categories=JACKETS),
                    product("b", 100, regular=200, categories=STYLE),
                    product("c", 100, regular=200, categories=[]),
                ],
            )
        ],
    )

    with session_scope(factory) as session:
        assert coverage(session) == [
            Coverage(site=FAKE_SITE.code, total=3, specific=1, catch_all=1, other=1)
        ]
