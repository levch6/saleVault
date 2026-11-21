import gzip
from datetime import UTC, datetime
from pathlib import Path

from salevault.scraper.base import Segment
from salevault.scraper.raw_archive import RawArchive


def test_save_writes_gzipped_files_with_safe_names(tmp_path: Path) -> None:
    archive = RawArchive(tmp_path, "prm", now=datetime(2026, 11, 21, 10, 0, tzinfo=UTC))

    archive.save(Segment(sex="M", price=(0, 5000)), 7, '{"ok": true}')

    path = tmp_path / "prm" / "20261121T100000Z" / "sex=M_price=0-5000__p007.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert fh.read() == '{"ok": true}'


def test_prune_keeps_the_newest_runs(tmp_path: Path) -> None:
    for hour in range(1, 5):
        RawArchive(tmp_path, "prm", now=datetime(2026, 11, 21, hour, tzinfo=UTC)).save(
            Segment(), 1, "{}"
        )

    removed = RawArchive(tmp_path, "prm", keep=2).prune()

    assert sorted(p.name for p in (tmp_path / "prm").iterdir()) == [
        "20261121T030000Z",
        "20261121T040000Z",
    ]
    assert len(removed) == 2
