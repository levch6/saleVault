"""Alembic helpers. Migrations live inside the package so they ship with it."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    config.attributes["engine"] = engine
    return config


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Apply migrations; refresh planner statistics if anything changed (new indexes have none,
    and SQLite then picks poor plans: a 200k catalog page went from 14 ms to 280 ms)."""
    before = current_revision(engine)
    command.upgrade(alembic_config(engine), revision)
    if current_revision(engine) != before:
        with engine.begin() as connection:
            connection.exec_driver_sql("ANALYZE")


def downgrade(engine: Engine, revision: str) -> None:
    command.downgrade(alembic_config(engine), revision)
