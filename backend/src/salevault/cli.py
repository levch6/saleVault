"""Command line interface: `salevault ...` or `python -m salevault ...`."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from salevault import __version__
from salevault.config import get_settings

app = typer.Typer(help="saleVault: sale items sorted by discount.", no_args_is_help=True)


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
