import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from salevault.db.maintenance import backup, compact_if_bloated, free_bytes, vacuum


def make_db(path: Path, rows: int = 20_000) -> Path:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT)")
        db.executemany("INSERT INTO t (payload) VALUES (?)", [("x" * 500,) for _ in range(rows)])
        db.commit()
    return path


def test_backup_copies_and_keeps_the_newest(tmp_path: Path) -> None:
    db = make_db(tmp_path / "salevault.db", rows=10)
    for hour in range(1, 5):
        backup(db, tmp_path / "backups", keep=2, now=datetime(2026, 11, 21, hour, tzinfo=UTC))

    kept = sorted(p.name for p in (tmp_path / "backups").iterdir())

    assert kept == ["salevault-20261121T030000Z.db", "salevault-20261121T040000Z.db"]
    with closing(sqlite3.connect(tmp_path / "backups" / kept[-1])) as copy:
        assert copy.execute("SELECT count(*) FROM t").fetchone()[0] == 10


def test_vacuum_reclaims_deleted_space(tmp_path: Path) -> None:
    db = make_db(tmp_path / "salevault.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DELETE FROM t")
        conn.commit()
    assert free_bytes(db) > 5_000_000

    assert compact_if_bloated(db, threshold=100_000_000) is None, "below the threshold"
    before, after = vacuum(db)

    assert after < before / 5
    assert free_bytes(db) == 0
