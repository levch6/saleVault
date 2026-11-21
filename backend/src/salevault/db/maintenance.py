"""Backups and compaction of the SQLite database (plain sqlite3, outside SQLAlchemy sessions)."""

import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

COMPACT_THRESHOLD_BYTES = 100_000_000
"""Staging is deleted after every run; SQLite keeps the pages. Compact past this much."""


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def backup(db_path: Path, backup_dir: Path, *, keep: int = 5, now: datetime | None = None) -> Path:
    """Consistent online copy (SQLite backup API), keeping the newest `keep` backups."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"salevault-{stamp}.db"
    with closing(_connect(db_path)) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
    for old in sorted(backup_dir.glob("salevault-*.db"), reverse=True)[keep:]:
        old.unlink()
    return target


def free_bytes(db_path: Path) -> int:
    with closing(_connect(db_path)) as connection:
        pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
    return int(pages) * int(size)


def vacuum(db_path: Path) -> tuple[int, int]:
    """Rewrite the file without free pages; returns (bytes before, bytes after)."""
    before = db_path.stat().st_size
    with closing(_connect(db_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return before, db_path.stat().st_size


def compact_if_bloated(db_path: Path, threshold: int = COMPACT_THRESHOLD_BYTES) -> int | None:
    """VACUUM when free pages exceed `threshold`; returns the bytes saved, or None."""
    if free_bytes(db_path) < threshold:
        return None
    before, after = vacuum(db_path)
    log.info("Compacted the database: %.0f MB -> %.0f MB", before / 1e6, after / 1e6)
    return before - after
