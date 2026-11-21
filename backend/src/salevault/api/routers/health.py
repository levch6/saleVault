from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from salevault import __version__
from salevault.api.deps import SessionDep

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    db: Literal["ok", "error"]


@router.get("/health")
def get_health(session: SessionDep) -> Health:
    try:
        session.execute(text("SELECT 1"))
        db: Literal["ok", "error"] = "ok"
    except Exception:
        db = "error"
    return Health(status="ok", version=__version__, db=db)
