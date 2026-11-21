"""Command line interface: `salevault ...` or `python -m salevault ...`."""

import asyncio
import json
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from alembic.migration import MigrationContext
from rich.console import Console
from rich.logging import RichHandler
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from salevault import __version__
from salevault.config import get_settings
from salevault.db.engine import create_db_engine, make_session_factory, sqlite_url
from salevault.db.migrate import upgrade
from salevault.db.runs import NothingToResumeError, RunAlreadyRunningError, RunRepository
from salevault.scraper.base import SiteAdapter
from salevault.scraper.browser import BrowserSession
from salevault.scraper.errors import ScrapeError
from salevault.scraper.raw_archive import RawArchive
from salevault.scraper.report import (
    RichProgress,
    make_progress,
    render_run_outcome,
    render_runs,
    render_summary,
)
from salevault.scraper.runner import RunOptions, ScrapeResult, ScrapeRunner
from salevault.scraper.service import RunOutcome, execute_run
from salevault.scraper.sites.registry import SITES, create_adapter, get_config

app = typer.Typer(help="saleVault: sale items sorted by discount.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
app.add_typer(db_app, name="db")
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
        force=True,
    )
    logging.getLogger("alembic").setLevel(logging.WARNING)


def _open_database() -> tuple[Engine, sessionmaker[Session]]:
    """Open the local DB, applying pending migrations first."""
    engine = create_db_engine(sqlite_url(get_settings().db_path))
    upgrade(engine)
    return engine, make_session_factory(engine)


@app.command()
def scrape(
    site: Annotated[str, typer.Argument(help="Site code (e.g. prm) or 'all'.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Collect and summarize without saving to the DB.")
    ] = False,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue the last failed or cancelled run.")
    ] = False,
    headed: Annotated[
        bool | None,
        typer.Option(
            "--headed/--headless",
            help="Visible browser window (via WSLg) or headless. Default: per site config.",
            show_default=False,
        ),
    ] = None,
    max_pages: Annotated[
        int | None, typer.Option(min=1, help="Debug: at most N pages per segment.")
    ] = None,
    save_raw: Annotated[
        bool, typer.Option(help="Archive raw API responses under data/raw (last 2 runs).")
    ] = True,
    jsonl: Annotated[
        Path | None, typer.Option(help="Also write normalized items to this JSONL file.")
    ] = None,
    top: Annotated[int, typer.Option(min=0, help="How many top discounts to print.")] = 20,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
    trigger: Annotated[str, typer.Option(hidden=True)] = "cli",
) -> None:
    """Scrape the sale section of a site and merge it into the local catalog."""
    codes = sorted(SITES) if site == "all" else [site]
    for code in codes:
        try:
            get_config(code)
        except KeyError as exc:
            raise typer.BadParameter(str(exc.args[0]), param_hint="SITE") from None
    if resume and dry_run:
        raise typer.BadParameter("--resume cannot be combined with --dry-run")

    _setup_logging(verbose)
    failed = False
    for code in codes:
        config = get_config(code)
        headless = config.headless if headed is None else not headed
        try:
            if dry_run:
                result = asyncio.run(
                    _dry_run(code, headless=headless, max_pages=max_pages, save_raw=save_raw)
                )
                render_summary(console, result, top=top)
            else:
                outcome = asyncio.run(
                    _persisted_run(
                        code,
                        headless=headless,
                        max_pages=max_pages,
                        save_raw=save_raw,
                        resume=resume,
                        trigger=trigger,
                    )
                )
                result = outcome.result
                render_summary(console, result, top=top)
                render_run_outcome(console, outcome)
        except (RunAlreadyRunningError, NothingToResumeError) as exc:
            console.print(f"[red]{code}: {exc}[/]")
            failed = True
            continue
        except ScrapeError as exc:
            console.print(f"[red]{code}: scrape failed: {exc}[/]")
            if not dry_run:
                console.print("Fetched pages are kept; continue with [bold]--resume[/].")
            failed = True
            continue
        except KeyboardInterrupt:
            console.print(f"[yellow]{code}: cancelled[/]" + _resume_hint(dry_run))
            raise typer.Exit(130) from None
        except asyncio.CancelledError:
            console.print(f"[yellow]{code}: terminated[/]" + _resume_hint(dry_run))
            raise typer.Exit(143) from None
        if jsonl is not None:
            _write_jsonl(jsonl, result)
            console.print(f"Items written to {jsonl}")
    if failed:
        raise typer.Exit(1)


def _resume_hint(dry_run: bool) -> str:
    return "" if dry_run else "; continue with --resume"


def _cancel_on_sigterm() -> None:
    """SIGTERM (e.g. Cancel in the UI) cancels the run cleanly, like Ctrl+C."""
    task = asyncio.current_task()
    if task is not None:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)


async def _dry_run(
    code: str, *, headless: bool, max_pages: int | None, save_raw: bool
) -> ScrapeResult:
    settings = get_settings()
    config = get_config(code)
    archive = RawArchive(settings.raw_dir, code) if save_raw else None
    options = RunOptions(concurrency=config.concurrency, max_pages_per_segment=max_pages)
    _cancel_on_sigterm()

    async with BrowserSession(settings.browser_profile_dir(code), headless=headless) as browser:
        adapter = create_adapter(code, browser)
        with make_progress(console) as progress:
            runner = ScrapeRunner(
                adapter,
                options,
                progress=RichProgress(progress, code),
                raw_sink=archive.save if archive else None,
            )
            result = await runner.run()

    _finish_archive(archive)
    return result


async def _persisted_run(
    code: str,
    *,
    headless: bool,
    max_pages: int | None,
    save_raw: bool,
    resume: bool,
    trigger: str,
) -> RunOutcome:
    settings = get_settings()
    config = get_config(code)
    archive = RawArchive(settings.raw_dir, code) if save_raw else None
    options = RunOptions(concurrency=config.concurrency, max_pages_per_segment=max_pages)
    _cancel_on_sigterm()

    @asynccontextmanager
    async def open_adapter() -> AsyncIterator[SiteAdapter]:
        profile = settings.browser_profile_dir(code)
        async with BrowserSession(profile, headless=headless) as browser:
            yield create_adapter(code, browser)

    engine, factory = _open_database()
    try:
        with make_progress(console) as progress:
            return await execute_run(
                open_adapter,
                config.site_info,
                factory,
                options=options,
                trigger=trigger,
                resume=resume,
                progress=RichProgress(progress, code),
                raw_sink=archive.save if archive else None,
            )
    finally:
        engine.dispose()
        _finish_archive(archive)


def _finish_archive(archive: RawArchive | None) -> None:
    if archive is not None and archive.run_dir.is_dir():
        archive.prune()
        console.print(f"Raw responses archived in {archive.run_dir}")


def _write_jsonl(path: Path, result: ScrapeResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in result.items.values():
            row = item.model_dump(mode="json")
            row["gender_mask"] = int(result.genders.get(item.external_id, 0))
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@app.command()
def runs(
    site: Annotated[str | None, typer.Option(help="Only runs of this site.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="How many runs to show.")] = 20,
) -> None:
    """Show recent scrape runs."""
    engine, factory = _open_database()
    try:
        rows = RunRepository(factory).list_runs(site=site, limit=limit)
    finally:
        engine.dispose()
    render_runs(console, rows)


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply pending migrations (scrapes do this automatically too)."""
    settings = get_settings()
    engine = create_db_engine(sqlite_url(settings.db_path))
    try:
        upgrade(engine)
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    console.print(f"Database {settings.db_path} is at revision {revision}")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind host (default from settings).")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port (default from settings).")] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes (dev).")] = False,
) -> None:
    """Run the API server; also serves the built UI if frontend/dist exists."""
    settings = get_settings()
    uvicorn.run(
        "salevault.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
    )


@app.command()
def openapi(
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write the schema.")],
) -> None:
    """Write the OpenAPI schema to a JSON file (used by `just gen-api`)."""
    from salevault.api.app import create_app

    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"OpenAPI schema written to {out}")
