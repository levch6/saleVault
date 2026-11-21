"""Alembic environment: reuses the app engine (pragmas, transactions) when one is passed in."""

from alembic import context
from sqlalchemy import Engine

from salevault.config import get_settings
from salevault.db.engine import create_db_engine, sqlite_url
from salevault.db.models import Base

config = context.config
target_metadata = Base.metadata


def _engine() -> Engine:
    engine = config.attributes.get("engine")
    if isinstance(engine, Engine):
        return engine
    url = config.get_main_option("sqlalchemy.url") or sqlite_url(get_settings().db_path)
    return create_db_engine(url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url") or sqlite_url(get_settings().db_path),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with _engine().connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
