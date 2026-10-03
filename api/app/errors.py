"""Error responses with field paths.

Every 422 has the shape
    {"detail": "<summary>", "errors": [{"path": "states[1].lef.tef", "message": "...", ...}]}
"""

from collections.abc import Sequence
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError


def loc_to_path(loc: Sequence[Any]) -> str:
    """("body", "states", 1, "lef", "tef", "min") -> "states[1].lef.tef.min"."""
    parts = list(loc)
    if parts and parts[0] == "body":
        parts = parts[1:]
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += ("." if out else "") + str(p)
    return out


def pydantic_errors(errors: Sequence[dict]) -> list[dict]:
    return [{"path": loc_to_path(e["loc"]), "message": e["msg"], "type": e["type"]} for e in errors]


def unprocessable(detail: str, errors: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": detail, "errors": errors or []})


class ApiError(Exception):
    """An error with a status code and an analyst-readable message."""

    def __init__(self, status: int, detail: str, errors: list[dict] | None = None):
        super().__init__(detail)
        self.status, self.detail, self.errors = status, detail, errors or []


async def request_validation_handler(_req: Request, exc: RequestValidationError) -> JSONResponse:
    return unprocessable("The request is not valid.", pydantic_errors(exc.errors()))


async def pydantic_validation_handler(_req: Request, exc: ValidationError) -> JSONResponse:
    return unprocessable("The document is not valid.", pydantic_errors(exc.errors()))


async def api_error_handler(_req: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "errors": exc.errors})
