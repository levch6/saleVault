from typing import Annotated

from fastapi import APIRouter, Path, Response

from salevault.api.deps import SessionDep, WriteSessionDep
from salevault.api.errors import ApiError, error_responses
from salevault.catalog import queries
from salevault.catalog.schemas import MAX_ID, FavoriteIn, FavoriteOut

router = APIRouter(tags=["favorites"])


@router.get("/favorites")
def list_favorites(session: SessionDep) -> list[FavoriteOut]:
    """Watchlist, newest first; includes items that left the sale."""
    return queries.list_favorites(session)


@router.put("/favorites/{product_id}", status_code=204, responses=error_responses(404))
def add_favorite(
    product_id: Annotated[int, Path(le=MAX_ID)],
    session: WriteSessionDep,
    body: FavoriteIn | None = None,
) -> Response:
    """Idempotent. The price at the moment of adding is kept to show the change since."""
    if not queries.add_favorite(session, product_id, body.note if body else None):
        raise ApiError(404, "not_found", f"Product {product_id} not found")
    return Response(status_code=204)


@router.delete("/favorites/{product_id}", status_code=204)
def remove_favorite(
    product_id: Annotated[int, Path(le=MAX_ID)], session: WriteSessionDep
) -> Response:
    queries.remove_favorite(session, product_id)
    return Response(status_code=204)
