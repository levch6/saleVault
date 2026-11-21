"""Console output for scrape runs: live progress and the final summary (Rich)."""

import os
from collections.abc import Iterable

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from salevault.db.runs import RunRow
from salevault.domain.models import Gender, ProductRecord
from salevault.scraper.runner import ScrapeResult
from salevault.scraper.service import RunOutcome

STATUS_STYLES = {
    "success": "green",
    "partial": "yellow",
    "failed": "red",
    "cancelled": "dim",
    "running": "cyan",
}

DISCOUNT_BUCKETS: tuple[tuple[int, int], ...] = (
    (70, 100),
    (60, 69),
    (50, 59),
    (40, 49),
    (30, 39),
    (0, 29),
)


def make_progress(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


class RichProgress:
    """`ProgressListener` that drives a Rich progress display."""

    def __init__(self, progress: Progress, site: str) -> None:
        self._progress = progress
        self._site = site
        self._planning = progress.add_task(f"[{site}] planning segments", total=None)
        self._pages: TaskID | None = None

    def on_planning(self, requests: int) -> None:
        self._progress.update(
            self._planning, description=f"[{self._site}] planning segments ({requests} requests)"
        )

    def on_planned(self, segments: int, pages_total: int) -> None:
        self._progress.update(
            self._planning,
            total=segments,
            completed=segments,
            description=f"[{self._site}] planned {segments} segments",
        )
        self._pages = self._progress.add_task(f"[{self._site}] pages", total=pages_total)

    def on_page(self, pages_done: int, items_seen: int) -> None:
        if self._pages is not None:
            self._progress.update(
                self._pages,
                completed=pages_done,
                description=f"[{self._site}] pages, {items_seen:,} items",
            )


def format_uah(minor: int) -> str:
    return f"{minor / 100:,.0f}".replace(",", " ") + " UAH"


def gender_label(mask: Gender) -> str:
    labels = [
        ("M", Gender.MEN),
        ("W", Gender.WOMEN),
        ("H", Gender.HOME),
        ("K", Gender.KIDS),
    ]
    return "+".join(code for code, flag in labels if mask & flag) or "-"


def top_discounts(items: Iterable[ProductRecord], n: int) -> list[ProductRecord]:
    return sorted(items, key=lambda p: (-p.discount_pct, -p.savings_minor))[:n]


def render_summary(console: Console, result: ScrapeResult, *, top: int = 20) -> None:
    duration = (result.finished_at - result.started_at).total_seconds()
    status = "[green]COMPLETE[/]" if result.complete else "[yellow]PARTIAL[/]"
    if result.limited:
        status += " (limited by --max-pages)"

    stats = Table(title=f"{result.site}: run summary", show_header=False)
    stats.add_column(style="bold")
    stats.add_column()
    stats.add_row("Status", status)
    stats.add_row("Duration", f"{duration / 60:.1f} min")
    stats.add_row(
        "Items",
        f"{result.item_count:,} unique of {result.expected_total:,} expected "
        f"({result.completeness:.1%})",
    )
    stats.add_row("Requests", f"{result.requests:,} (retries: {result.retries})")
    stats.add_row("Invalid items skipped", str(result.invalid_items))
    console.print(stats)

    segments = Table(title="Segments")
    for col in ("Segment", "Expected", "Fetched", "Pages", "Coverage"):
        segments.add_column(col, justify="left" if col == "Segment" else "right")
    for s in result.segments:
        coverage = f"{s.ratio:.1%}" + (" TRUNCATED" if s.truncated else "")
        style = None if s.ratio >= result.segment_threshold and not s.truncated else "yellow"
        segments.add_row(
            s.key, f"{s.expected:,}", f"{s.fetched:,}", str(s.pages), coverage, style=style
        )
    console.print(segments)

    buckets = Table(title="Discount distribution")
    buckets.add_column("Discount")
    buckets.add_column("Items", justify="right")
    for low, high in DISCOUNT_BUCKETS:
        n = sum(count for pct, count in result.discount_counts.items() if low <= pct <= high)
        label = f">= {low}%" if high == 100 else f"{low}-{high}%"
        buckets.add_row(label, f"{n:,}")
    console.print(buckets)

    best = Table(title=f"Top {top} discounts")
    for col in ("Disc", "Gender", "Brand", "Name", "Price", "Was", "In stock"):
        best.add_column(col, justify="right" if col in ("Disc", "Price", "Was") else "left")
    for p in top_discounts(result.top, top):
        in_stock = ", ".join(s.label for s in p.sizes if s.in_stock) or "-"
        best.add_row(
            f"-{p.discount_pct}%",
            gender_label(result.genders.get(p.external_id, Gender(0))),
            p.brand.name,
            p.name if len(p.name) <= 48 else p.name[:47] + "...",
            format_uah(p.price_minor),
            format_uah(p.price_regular_minor),
            in_stock if len(in_stock) <= 24 else in_stock[:23] + "...",
        )
    console.print(best)


def render_run_outcome(console: Console, outcome: RunOutcome) -> None:
    s = outcome.stats
    style = STATUS_STYLES.get(outcome.status, "")
    table = Table(title=f"Run #{outcome.run_id}: catalog changes", show_header=False)
    table.add_column(style="bold")
    table.add_column(justify="right")
    table.add_row("Status", f"[{style}]{outcome.status}[/]")
    table.add_row("Items seen", f"{s.seen:,}")
    table.add_row("New", f"{s.new:,}")
    table.add_row("Price drops", f"{s.price_drops:,}")
    table.add_row("Price increases", f"{s.price_ups:,}")
    table.add_row("Back in sale", f"{s.returned:,}")
    table.add_row("Not seen (grace period)", f"{s.missing:,}")
    table.add_row("Removed from sale", f"{s.removed:,}")
    console.print(table)
    if outcome.status == "partial":
        console.print("[yellow]Partial run: the catalog was updated, but nothing was removed.[/]")


def render_runs(console: Console, rows: list[RunRow]) -> None:
    if not rows:
        # In the container image there is no `just`; the CLI itself is on the PATH.
        command = (
            "salevault scrape prm" if os.environ.get("SALEVAULT_CONTAINER") else "just scrape prm"
        )
        console.print(f"No runs yet. Start one with [bold]{command}[/].")
        return
    table = Table(title="Scrape runs")
    for col in ("#", "Site", "Status", "Trigger", "Started", "Duration", "Items", "New", "Drops"):
        table.add_column(col, justify="right" if col in ("#", "Items", "New", "Drops") else "left")
    table.add_column("Removed", justify="right")
    table.add_column("Error")
    for r in rows:
        stats = r.stats or {}
        duration = (
            f"{(r.finished_at - r.started_at).total_seconds() / 60:.1f} min"
            if r.finished_at
            else "-"
        )
        items = f"{r.items_seen:,}" + (f" / {r.expected_total:,}" if r.expected_total else "")
        table.add_row(
            str(r.id),
            r.site,
            f"[{STATUS_STYLES.get(r.status, '')}]{r.status}[/]",
            r.trigger,
            r.started_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            duration,
            items,
            str(stats.get("new", "-")),
            str(stats.get("price_drops", "-")),
            str(stats.get("removed", "-")),
            (r.error or "")[:60],
        )
    console.print(table)
