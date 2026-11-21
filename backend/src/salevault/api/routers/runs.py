from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from salevault.api.deps import FactoryDep, LauncherDep, SessionDep
from salevault.api.errors import ApiError, error_responses
from salevault.api.schemas import RunOut, SiteOut, StartRunIn, StartRunOut
from salevault.db.models import Product, Site
from salevault.db.runs import RunRepository
from salevault.scraper.sites.registry import SITES

router = APIRouter(tags=["runs"])

FINISHED = ("success", "partial")


@router.get("/sites")
def list_sites(session: SessionDep, factory: FactoryDep) -> list[SiteOut]:
    """Known shops with their catalog size and latest runs (also shops never scraped yet)."""
    db_sites = {s.code: s for s in session.scalars(select(Site))}
    counts = {  # noqa: C416 (dict(Result) breaks: Result has .keys())
        code: n
        for code, n in session.execute(
            select(Site.code, func.count(Product.id))
            .join(Product, Product.site_id == Site.id)
            .where(Product.is_active.is_(True))
            .group_by(Site.code)
        )
    }
    repo = RunRepository(factory)
    out = []
    for code in sorted(set(SITES) | set(db_sites)):
        config = SITES.get(code)
        db_site = db_sites.get(code)
        runs = repo.list_runs(site=code, limit=50)
        completed = next((r for r in runs if r.status in FINISHED), None)
        out.append(
            SiteOut(
                code=code,
                name=config.display_name if config else db_site.name if db_site else code,
                origin=config.origin if config else db_site.origin if db_site else "",
                active_products=counts.get(code, 0),
                last_completed=RunOut.from_row(completed) if completed else None,
                latest=RunOut.from_row(runs[0]) if runs else None,
            )
        )
    return out


@router.get("/runs")
def list_runs(
    factory: FactoryDep,
    site: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[RunOut]:
    return [RunOut.from_row(r) for r in RunRepository(factory).list_runs(site=site, limit=limit)]


@router.get("/runs/{run_id}", responses=error_responses(404))
def get_run(run_id: int, factory: FactoryDep) -> RunOut:
    """Poll this while `status` is `running` to show progress."""
    row = RunRepository(factory).find(run_id)
    if row is None:
        raise ApiError(404, "not_found", f"Run {run_id} not found")
    return RunOut.from_row(row)


@router.post("/runs", status_code=202, responses=error_responses(409, 422, 500))
async def start_run(body: StartRunIn, launcher: LauncherDep) -> StartRunOut:
    """Start a scrape in the background; returns once the run is registered."""
    codes = sorted(SITES) if body.site == "all" else [body.site]
    unknown = [c for c in codes if c not in SITES]
    if unknown:
        raise ApiError(422, "unknown_site", f"Unknown site {unknown[0]!r}")
    run_ids = [await launcher.start(code, headed=body.headed) for code in codes]
    return StartRunOut(run_ids=run_ids)


@router.post("/runs/{run_id}/cancel", status_code=202, responses=error_responses(404, 409))
def cancel_run(run_id: int, launcher: LauncherDep) -> RunOut:
    """Ask the scraper to stop; it finishes as `cancelled` and can be resumed from the CLI."""
    try:
        row = launcher.cancel(run_id)
    except KeyError:
        raise ApiError(404, "not_found", f"Run {run_id} not found") from None
    return RunOut.from_row(row)
