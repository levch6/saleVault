"""API models for runs, sites and errors (catalog models live in salevault.catalog.schemas)."""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from salevault.db.runs import RunRow

RunStatus = Literal["running", "success", "partial", "failed", "cancelled"]


class ErrorOut(BaseModel):
    detail: str
    code: str


class RunOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    site: str
    status: RunStatus
    trigger: Literal["cli", "ui"]
    started_at: datetime
    finished_at: datetime | None
    expected_total: int | None
    pages_total: int | None
    pages_done: int
    items_seen: int
    stats: dict[str, Any] | None
    error: str | None

    @classmethod
    def from_row(cls, row: RunRow) -> Self:
        return cls.model_validate(
            {
                "id": row.id,
                "site": row.site,
                "status": row.status,
                "trigger": row.trigger,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "expected_total": row.expected_total,
                "pages_total": row.pages_total,
                "pages_done": row.pages_done,
                "items_seen": row.items_seen,
                "stats": dict(row.stats) if row.stats is not None else None,
                "error": row.error,
            }
        )


class SiteOut(BaseModel):
    code: str
    name: str
    origin: str
    active_products: int
    last_completed: RunOut | None
    """Latest success or partial run: the data the catalog shows."""
    latest: RunOut | None
    """Latest run of any status (running, failed...)."""


class StartRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(description="Site code, or 'all' for every known site")
    headed: bool | None = Field(None, description="Override the site's browser mode")


class StartRunOut(BaseModel):
    run_ids: list[int]
    skipped: list[str] = Field(
        default_factory=list, description="With site=all: shops that could not start, and why"
    )
