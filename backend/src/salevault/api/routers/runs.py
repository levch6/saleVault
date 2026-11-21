from typing import Annotated

from fastapi import APIRouter, Path, Query
from sqlalchemy import func, select

from salevault.api.deps import LauncherDep, RunsDep, SessionDep
from salevault.api.errors import ApiError, error_responses
from salevault.api.launcher import LaunchError
from salevault.api.schemas import RunOut, SiteOut, StartRunIn, StartRunOut
from salevault.catalog.schemas import MAX_ID
from salevault.db.models import Product, Site
from salevault.db.runs import RunAlreadyRunningError
from salevault.scraper.sites.registry import SITES

router = APIRouter(tags=["runs"])

FINISHED = ("success", "partial")


@router.get("/sites")
def list_sites(session: SessionDep, repo: RunsDep) -> list[SiteOut]:
    """Known shops with their catalog size and latest runs (also shops never scraped yet)."""
    repo.reap_dead()  # a crashed scraper must not look like it is still running
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
    out = []
    for code in sorted(set(SITES) | set(db_sites)):
        config = SITES.get(code)
        db_site = db_sites.get(code)
        latest = repo.latest(code)
        completed = repo.latest(code, statuses=FINISHED)
        out.append(
            SiteOut(
                code=code,
                name=config.display_name if config else db_site.name if db_site else code,
                origin=config.origin if config else db_site.origin if db_site else "",
                active_products=counts.get(code, 0),
                last_completed=RunOut.from_row(completed) if completed else None,
                latest=RunOut.from_row(latest) if latest else None,
            )
        )
    return out


@router.get("/runs")
def list_runs(
    repo: RunsDep,
    site: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[RunOut]:
    repo.reap_dead()
    return [RunOut.from_row(r) for r in repo.list_runs(site=site, limit=limit)]


@router.get("/runs/{run_id}", responses=error_responses(404))
def get_run(run_id: Annotated[int, Path(le=MAX_ID)], repo: RunsDep) -> RunOut:
    """Poll this while `status` is `running` to show progress."""
    repo.reap_dead()
    row = repo.find(run_id)
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
    run_ids: list[int] = []
    skipped: list[str] = []
    for code in codes:
        try:
            run_ids.append(await launcher.start(code, headed=body.headed))
        except (RunAlreadyRunningError, LaunchError) as exc:
            if len(codes) == 1:
                raise
            skipped.append(str(exc))  # "all": start the other shops anyway
    if not run_ids:
        raise RunAlreadyRunningError("; ".join(skipped))
    return StartRunOut(run_ids=run_ids, skipped=skipped)


@router.post("/runs/{run_id}/cancel", status_code=202, responses=error_responses(404, 409))
def cancel_run(run_id: Annotated[int, Path(le=MAX_ID)], launcher: LauncherDep) -> RunOut:
    """Ask the scraper to stop; it finishes as `cancelled` and can be resumed from the CLI."""
    try:
        row = launcher.cancel(run_id)
    except KeyError:
        raise ApiError(404, "not_found", f"Run {run_id} not found") from None
    return RunOut.from_row(row)
