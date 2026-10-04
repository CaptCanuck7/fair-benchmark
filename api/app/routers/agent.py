"""Agent status and the outbound request log, for the browser."""

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import OutboundLogRow

router = APIRouter(prefix="/api/agent", tags=["agent"])

NOT_RUNNING = "The agent service isn’t running. Start it with docker compose up."


def fetch_agent_status() -> dict:
    """Ask the agent service whether it is configured. Never raises."""
    try:
        res = httpx.get(f"{settings.agent_url}/status", timeout=3.0)
        res.raise_for_status()
        data = res.json()
    except (httpx.HTTPError, ValueError):
        return {"configured": False, "reason": NOT_RUNNING, "model": None, "externalEnabled": False}
    return {
        "configured": bool(data.get("configured")),
        "reason": data.get("reason"),
        "model": data.get("model"),
        "externalEnabled": bool(data.get("externalEnabled")),
        "allowedDomains": data.get("allowedDomains", []),
    }


@router.get("/status")
def agent_status() -> dict:
    return fetch_agent_status()


@router.get("/outbound-log")
def outbound_log(limit: int = Query(default=200, ge=1, le=1000), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(OutboundLogRow).order_by(OutboundLogRow.id.desc()).limit(limit)).all()
    return [
        {
            "id": r.id, "agentRunId": r.agent_run_id, "tool": r.tool, "destination": r.destination,
            "query": r.query, "allowed": r.allowed, "blockedReason": r.blocked_reason, "at": r.at,
        }
        for r in rows
    ]
