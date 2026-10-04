"""Read-only internal evidence for the agent service.

These routes live under /internal, which nginx does not proxy, so only
containers on the compose network can reach them.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.evidence import SHEETS, SHEETS_BY_SLUG, query_sheet

router = APIRouter(prefix="/internal/evidence", tags=["internal-evidence"])


@router.get("")
def list_sheets() -> list[dict]:
    return [{"slug": s.slug, "sheet": s.title} for s in SHEETS]


@router.get("/{sheet}")
def get_sheet(
    sheet: str,
    asset_id: list[str] | None = Query(default=None),
    type: str | None = Query(default=None, max_length=120),
    session: Session = Depends(get_session),
) -> dict:
    s = SHEETS_BY_SLUG.get(sheet)
    if s is None:
        raise ApiError(404, f"Unknown evidence sheet. Use one of: {', '.join(SHEETS_BY_SLUG)}.")
    if type and s.slug != "incidents":
        raise ApiError(422, "The type filter applies only to incidents.")
    return {"sheet": s.title, "items": query_sheet(session, s, asset_id, type)}
