"""Domain errors -> JSON `{"detail": ..., "code": ...}` responses."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from salevault.api.launcher import LaunchError, RunNotRunningError
from salevault.api.schemas import ErrorOut
from salevault.db.runs import RunAlreadyRunningError


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation for error responses, so the TS client knows their shape."""
    return {status: {"model": ErrorOut} for status in statuses}


def _json(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _json(exc.status, exc.code, exc.detail)

    @app.exception_handler(RunAlreadyRunningError)
    async def _already_running(_request: Request, exc: RunAlreadyRunningError) -> JSONResponse:
        return _json(409, "run_already_running", str(exc))

    @app.exception_handler(RunNotRunningError)
    async def _not_running(_request: Request, exc: RunNotRunningError) -> JSONResponse:
        return _json(409, "run_not_running", str(exc))

    @app.exception_handler(LaunchError)
    async def _launch_failed(_request: Request, exc: LaunchError) -> JSONResponse:
        return _json(500, "launch_failed", str(exc))
