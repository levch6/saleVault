"""Command line interface: `salevault ...` or `python -m salevault ...`."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.logging import RichHandler

from salevault import __version__
from salevault.config import get_settings
from salevault.scraper.browser import BrowserSession
from salevault.scraper.errors import ScrapeError
from salevault.scraper.raw_archive import RawArchive
from salevault.scraper.report import RichProgress, make_progress, render_summary
from salevault.scraper.runner import RunOptions, ScrapeResult, ScrapeRunner
from salevault.scraper.sites.registry import SITES, create_adapter, get_config

app = typer.Typer(help="saleVault: sale items sorted by discount.", no_args_is_help=True)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
        force=True,
    )


@app.command()
def scrape(
    site: Annotated[str, typer.Argument(help="Site code (e.g. prm) or 'all'.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Collect and summarize without saving to the DB.")
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
) -> None:
    """Scrape the sale section of a site."""
    if not dry_run:
        console.print("[red]Saving to the database is not implemented yet; use --dry-run.[/]")
        raise typer.Exit(2)
    codes = sorted(SITES) if site == "all" else [site]
    for code in codes:
        try:
            get_config(code)
        except KeyError as exc:
            raise typer.BadParameter(str(exc.args[0]), param_hint="SITE") from None

    _setup_logging(verbose)
    failed = False
    for code in codes:
        try:
            headless = get_config(code).headless if headed is None else not headed
            result = asyncio.run(
                _scrape_site(code, headless=headless, max_pages=max_pages, save_raw=save_raw)
            )
        except ScrapeError as exc:
            console.print(f"[red]{code}: scrape failed: {exc}[/]")
            failed = True
            continue
        except KeyboardInterrupt:
            console.print(f"[yellow]{code}: cancelled[/]")
            raise typer.Exit(130) from None
        render_summary(console, result, top=top)
        if jsonl is not None:
            _write_jsonl(jsonl, result)
            console.print(f"Items written to {jsonl}")
    if failed:
        raise typer.Exit(1)


async def _scrape_site(
    code: str, *, headless: bool, max_pages: int | None, save_raw: bool
) -> ScrapeResult:
    settings = get_settings()
    config = get_config(code)
    archive = RawArchive(settings.raw_dir, code) if save_raw else None
    options = RunOptions(concurrency=config.concurrency, max_pages_per_segment=max_pages)

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

    if archive is not None:
        archive.prune()
        console.print(f"Raw responses archived in {archive.run_dir}")
    return result


def _write_jsonl(path: Path, result: ScrapeResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in result.items.values():
            row = item.model_dump(mode="json")
            row["gender_mask"] = int(result.genders.get(item.external_id, 0))
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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
