"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from salevault import __version__
from salevault.api.errors import install_error_handlers
from salevault.api.launcher import CommandFactory, RunLauncher, scrape_command
from salevault.api.routers import catalog, favorites, health, runs, settings
from salevault.catalog import queries
from salevault.catalog.schemas import FacetsQuery
from salevault.config import Settings, get_settings
from salevault.db.engine import create_db_engine, make_session_factory, session_scope, sqlite_url
from salevault.db.migrate import upgrade
from salevault.db.runs import RunRepository

log = logging.getLogger(__name__)


def _operation_id(route: APIRoute) -> str:
    # Short, stable operation ids (e.g. "get_health") for the generated TS client.
    return route.name


def create_app(
    config: Settings | None = None, *, scrape_command_factory: CommandFactory = scrape_command
) -> FastAPI:
    config = config or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(sqlite_url(config.db_path))
        upgrade(engine)
        factory = make_session_factory(engine)
        write_factory = make_session_factory(engine, write=True)

        def warm_facets() -> None:
            """The unfiltered facets are the first thing the UI asks for; compute them early."""
            try:
                with session_scope(factory) as session:
                    queries.facets(session, FacetsQuery(heavy=False))
                    queries.facets(session, FacetsQuery())
            except Exception:
                log.exception("Warming the facet cache failed")

        app.state.factory = factory
        app.state.write_factory = write_factory
        app.state.launcher = RunLauncher(
            RunRepository(write_factory, reader=factory),
            data_dir=config.data_dir,
            command=scrape_command_factory,
            on_finish=warm_facets,
        )
        app.state.warmup = asyncio.create_task(asyncio.to_thread(warm_facets))
        try:
            yield
        finally:
            await app.state.warmup
            engine.dispose()

    app = FastAPI(
        title="saleVault",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    for router in (health.router, catalog.router, favorites.router, settings.router, runs.router):
        app.include_router(router, prefix="/api")
    _mount_frontend(app, config.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA (if present) with a fallback to index.html for client-side routes."""
    index = dist / "index.html"
    if not index.is_file():
        return

    root = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
