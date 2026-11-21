from fastapi import APIRouter

from salevault.api.deps import SessionDep, WriteSessionDep
from salevault.catalog import queries
from salevault.catalog.schemas import SettingsIn, SettingsOut

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings(session: SessionDep) -> SettingsOut:
    return queries.read_settings(session)


@router.put("/settings")
def update_settings(body: SettingsIn, session: WriteSessionDep) -> SettingsOut:
    """Partial update: omitted fields keep their value."""
    return queries.update_settings(session, body)
