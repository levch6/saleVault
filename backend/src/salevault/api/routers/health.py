from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from salevault import __version__

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@router.get("/health")
async def get_health() -> Health:
    return Health(status="ok", version=__version__)
