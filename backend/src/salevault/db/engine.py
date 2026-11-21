"""SQLite engine with WAL, foreign keys and proper transactions."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    # The API serves requests from a thread pool; pooled connections are never shared at once.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
        # Let SQLAlchemy own transaction boundaries (pysqlite's implicit BEGIN breaks them).
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=5000",
            # Facets aggregate the whole catalog: a bigger page cache and mmap roughly halve that.
            "PRAGMA cache_size=-65536",
            "PRAGMA mmap_size=268435456",
            "PRAGMA temp_store=MEMORY",
        ):
            cursor.execute(pragma)
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


def analyze(factory: sessionmaker[Session]) -> None:
    """Refresh planner statistics; without them SQLite prefers a poor index for facet scans."""
    with session_scope(factory) as session:
        session.execute(text("ANALYZE"))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
