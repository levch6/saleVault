"""Gzipped raw API responses per run, for debugging and refreshing test fixtures."""

import gzip
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from salevault.scraper.base import Segment

_UNSAFE = re.compile(r"[^A-Za-z0-9=.-]+")


class RawArchive:
    """Writes `<root>/<site>/<timestamp>/<segment>__pNNN.json.gz` and keeps the newest runs."""

    def __init__(
        self, root: Path, site: str, *, keep: int = 2, now: datetime | None = None
    ) -> None:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        self.site_dir = root / site
        self.run_dir = self.site_dir / stamp
        self._keep = keep

    def save(self, segment: Segment, page: int, text: str) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        name = f"{_UNSAFE.sub('_', segment.key)}__p{page:03d}.json.gz"
        with gzip.open(self.run_dir / name, "wt", encoding="utf-8") as fh:
            fh.write(text)

    def prune(self) -> list[Path]:
        """Delete all but the newest `keep` run directories; returns what was removed."""
        if not self.site_dir.is_dir():
            return []
        runs = sorted((p for p in self.site_dir.iterdir() if p.is_dir()), reverse=True)
        removed = runs[self._keep :]
        for path in removed:
            shutil.rmtree(path)
        return removed
