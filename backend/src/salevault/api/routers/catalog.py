from typing import Annotated

from fastapi import APIRouter, Query

from salevault.api.deps import SessionDep
from salevault.api.errors import ApiError, error_responses
from salevault.catalog import queries
from salevault.catalog.schemas import (
    CatalogQuery,
    Facets,
    ProductDetail,
    ProductPage,
    ProductsQuery,
)

router = APIRouter(tags=["catalog"])


@router.get("/products")
def list_products(query: Annotated[ProductsQuery, Query()], session: SessionDep) -> ProductPage:
    """Sale items, by default sorted by discount, biggest first."""
    return queries.list_products(session, query)


@router.get("/facets")
def get_facets(query: Annotated[CatalogQuery, Query()], session: SessionDep) -> Facets:
    """Counts per filter value; each facet ignores its own filter."""
    return queries.facets(session, query)


@router.get("/products/{product_id}", responses=error_responses(404))
def get_product(product_id: int, session: SessionDep) -> ProductDetail:
    detail = queries.product_detail(session, product_id)
    if detail is None:
        raise ApiError(404, "not_found", f"Product {product_id} not found")
    return detail
