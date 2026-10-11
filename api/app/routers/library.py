"""The reference library of annual-report figures (AGENT_BUILD.md section 7).

It ships empty. Figures come from the library refresh task (proposed, then
approved or rejected by an analyst) or are added by hand. Only approved
entries are used as evidence.
"""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_pipeline
from app.agent_client import fetch_agent_status
from app.db import get_session
from app.errors import ApiError
from app.models import ReferenceLibraryRow
from app.routers.register import reviewer_name
from app.schemas import now_iso

router = APIRouter(prefix="/api/library", tags=["library"])
internal = APIRouter(prefix="/internal/library", tags=["internal-library"])

LIBRARY_FILE = "reference_library.json"


def citation(r: ReferenceLibraryRow) -> str:
    """How evidence cites a library entry: report, edition, page and URL."""
    page = f", p. {r.page}" if r.page else ""
    return f"{r.source} {r.edition}{page}: {r.url}"


def entry_out(r: ReferenceLibraryRow) -> dict:
    return {
        "id": r.id, "metric": r.metric, "value": r.value, "unit": r.unit, "segment": r.segment,
        "source": r.source, "edition": r.edition, "url": r.url, "page": r.page, "retrievedAt": r.retrieved_at,
        "approvedBy": r.approved_by, "status": r.status, "quote": r.quote, "agentRunId": r.agent_run_id,
        "citation": citation(r),
    }


class EntryIn(BaseModel):
    metric: str = Field(min_length=3, max_length=300)
    value: float
    unit: str = Field(min_length=1, max_length=100)
    segment: str | None = Field(default=None, max_length=200)
    source: str = Field(min_length=2, max_length=200)
    edition: str = Field(min_length=2, max_length=100)
    url: HttpUrl
    page: str | None = Field(default=None, max_length=32)
    quote: str | None = Field(default=None, max_length=1000)


class Review(BaseModel):
    action: Literal["approve", "reject", "edit"]
    entry: EntryIn | None = None


@router.get("")
def list_entries(status: str | None = Query(default=None), session: Session = Depends(get_session)) -> list[dict]:
    q = select(ReferenceLibraryRow).order_by(ReferenceLibraryRow.source, ReferenceLibraryRow.metric)
    if status:
        q = q.where(ReferenceLibraryRow.status == status)
    return [entry_out(r) for r in session.scalars(q)]


@router.post("", status_code=201)
def add_entry(body: EntryIn, session: Session = Depends(get_session)) -> dict:
    """An analyst's own entry, approved by them as it is added."""
    r = ReferenceLibraryRow(**body.model_dump(mode="json"), retrieved_at=now_iso(), status="approved",
                            approved_by=reviewer_name())
    session.add(r)
    session.commit()
    return entry_out(r)


@router.put("/{entry_id}")
def review_entry(entry_id: int, body: Review, session: Session = Depends(get_session)) -> dict:
    r = session.get(ReferenceLibraryRow, entry_id)
    if r is None:
        raise ApiError(404, "Library entry not found.")
    if body.action == "edit":
        if body.entry is None:
            raise ApiError(422, "Send the edited entry.", [{"path": "entry", "message": "Required."}])
        for k, v in body.entry.model_dump(mode="json").items():
            setattr(r, k, v)
        r.status, r.approved_by = "approved", reviewer_name()
    elif body.action == "approve":
        r.status, r.approved_by = "approved", reviewer_name()
    else:
        r.status, r.approved_by = "rejected", None
    session.commit()
    return entry_out(r)


@router.post("/refresh", status_code=202)
def refresh(session: Session = Depends(get_session)) -> dict:
    """Ask the agent to propose entries from the allowlisted report pages."""
    status = fetch_agent_status()
    if not status["configured"]:
        raise ApiError(503, status["reason"] or "The agent is off.")
    if not status.get("externalEnabled"):
        raise ApiError(409, "External sources are turned off, so the library can’t be refreshed from the web.")
    try:
        return {"runId": agent_pipeline.queue_library_refresh(session)}
    except agent_pipeline.TaskBlocked as exc:
        raise ApiError(409, str(exc)) from exc


@internal.get("")
def search_approved(q: str = Query(default="", max_length=200), limit: int = Query(default=20, ge=1, le=100),
                    session: Session = Depends(get_session)) -> list[dict]:
    """Approved entries matching any word of `q`, best first (all of them when q is empty)."""
    words = [w for w in q.lower().split() if len(w) > 2]
    rows = session.scalars(select(ReferenceLibraryRow).where(ReferenceLibraryRow.status == "approved")).all()

    def score(r: ReferenceLibraryRow) -> int:
        text = f"{r.metric} {r.segment or ''} {r.source} {r.unit}".lower()
        return sum(w in text for w in words)

    ranked = sorted(rows, key=score, reverse=True) if words else list(rows)
    return [entry_out(r) for r in ranked if not words or score(r)][:limit]


def seed_library(session: Session, folder: Path) -> int:
    """Load agent-data/reference_library.json once, into an empty table, as
    approved entries. The file ships with an empty entries list."""
    path = folder / LIBRARY_FILE
    if not path.is_file() or session.scalars(select(ReferenceLibraryRow.id).limit(1)).first():
        return 0
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or []
    for e in entries:
        body = EntryIn.model_validate(e)
        session.add(ReferenceLibraryRow(**body.model_dump(mode="json"), retrieved_at=e.get("retrieved_at") or now_iso(),
                                        status="approved", approved_by=e.get("approved_by") or "seed file"))
    session.commit()
    return len(entries)
