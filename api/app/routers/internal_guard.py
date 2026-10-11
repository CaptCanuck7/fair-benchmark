"""Internal endpoints the agent's outbound guard relies on. Not proxied by nginx."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app import app_settings
from app.identifiers import build_identifiers
from app.models import OutboundLogRow
from app.schemas import now_iso

router = APIRouter(prefix="/internal", tags=["internal-guard"])


@router.get("/guard/identifiers")
def identifiers(session: Session = Depends(get_session)) -> list[dict]:
    return build_identifiers(session)


class OutboundLogIn(BaseModel):
    agent_run_id: str | None = Field(default=None, max_length=64)
    tool: str = Field(max_length=64)
    destination: str = Field(max_length=2048)
    query: str | None = Field(default=None, max_length=2048)
    allowed: bool
    blocked_reason: str | None = Field(default=None, max_length=128)


@router.post("/outbound-log", status_code=201)
def write_outbound_log(entry: OutboundLogIn, session: Session = Depends(get_session)) -> dict:
    row = OutboundLogRow(**entry.model_dump(), at=now_iso())
    session.add(row)
    session.commit()
    return {"id": row.id}


@router.get("/guard/agent-config")
def agent_config(session: Session = Depends(get_session)) -> dict:
    """Settings-page overrides the agent merges with its .env values."""
    return app_settings.agent_overrides(session)
