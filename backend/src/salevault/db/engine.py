"""SQLite engine with WAL, foreign keys and proper transactions."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

BUSY_TIMEOUT_MS = 120_000
"""How long a write waits for another writer. Longer than the slowest merge of a big catalog
(about 40 s), so a second scraper or an API write waits instead of failing."""


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
            f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
            # Facets aggregate the whole catalog: a bigger page cache and mmap roughly halve that.
            "PRAGMA cache_size=-65536",
            "PRAGMA mmap_size=268435456",
            "PRAGMA temp_store=MEMORY",
        ):
            cursor.execute(pragma)
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        mode = connection.get_execution_options().get("sqlite_begin", "")
        connection.exec_driver_sql(f"BEGIN {mode}".rstrip())

    return engine


def analyze(factory: sessionmaker[Session]) -> None:
    """Refresh planner statistics; without them SQLite prefers a poor index for facet scans."""
    with session_scope(factory) as session:
        session.execute(text("ANALYZE"))


def make_session_factory(engine: Engine, *, write: bool = False) -> sessionmaker[Session]:
    """Sessions for reads, or with `write=True` for transactions that write.

    Writers start with `BEGIN IMMEDIATE`. A deferred transaction that reads first has to upgrade
    its lock when it writes, and SQLite fails that upgrade at once, ignoring the busy timeout,
    when another connection has written in between. Readers stay deferred: in WAL mode they
    never wait for writers.
    """
    bind = engine.execution_options(sqlite_begin="IMMEDIATE") if write else engine
    return sessionmaker(bind, expire_on_commit=False)


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
