"""Analyst-editable settings (AGENT_BUILD.md section 12)."""

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app import app_settings
from app.config import settings
from app.db import get_session
from app.errors import ApiError

router = APIRouter(prefix="/api/settings", tags=["settings"])

KEYS = {"analystName", "triageMinScore", "externalEnabled", "extraDomains", "removedDomains"}


def settings_out(session: Session) -> dict:
    o = app_settings.agent_overrides(session)
    return {
        "analystName": settings.analyst_name or None,
        "triageMinScore": settings.triage_min_score,
        "externalEnabled": o["externalEnabled"],
        "extraDomains": o["extraDomains"],
        "removedDomains": o["removedDomains"],
    }


@router.get("")
def get_settings(session: Session = Depends(get_session)) -> dict:
    return settings_out(session)


@router.put("")
def put_settings(changes: dict[str, Any] = Body(...), session: Session = Depends(get_session)) -> dict:
    """Change any of analystName, triageMinScore, externalEnabled (null follows
    .env), extraDomains and removedDomains."""
    unknown = set(changes) - KEYS
    if unknown:
        raise ApiError(422, f"Unknown settings: {', '.join(sorted(unknown))}.")
    try:
        app_settings.update(session, changes)
    except app_settings.SettingsError as exc:
        raise ApiError(422, str(exc), [{"path": exc.path, "message": str(exc)}]) from exc
    return settings_out(session)
