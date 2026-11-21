"""Alembic helpers. Migrations live inside the package so they ship with it."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from salevault.db.maintenance import backup

log = logging.getLogger(__name__)

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
    and SQLite then picks poor plans: a 200k catalog page went from 14 ms to 280 ms).

    An existing database is backed up first: favorites and the price history cannot be
    scraped again if a migration goes wrong.
    """
    config = alembic_config(engine)
    before = current_revision(engine)
    target = (
        ScriptDirectory.from_config(config).get_current_head() if revision == "head" else revision
    )
    database = engine.url.database
    if before is not None and before != target and database and database != ":memory:":
        path = Path(database)
        saved = backup(path, path.parent / "backups")
        log.info("Backed up the database to %s before migrating", saved)
    command.upgrade(config, revision)
    if current_revision(engine) != before:
        with engine.begin() as connection:
            connection.exec_driver_sql("ANALYZE")


def downgrade(engine: Engine, revision: str) -> None:
    command.downgrade(alembic_config(engine), revision)
