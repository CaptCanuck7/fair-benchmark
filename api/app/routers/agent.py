"""Agent status, agent jobs and the outbound request log, for the browser."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import agent_pipeline
from app.agent_client import fetch_agent_status
from app.config import settings
from app.db import get_session
from app.errors import ApiError
from app.models import AgentRunRow, OutboundLogRow, RiskRow
from app.routers.register import get_risk, queue_checks, run_out

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/status")
def agent_status() -> dict:
    return {**fetch_agent_status(), "triageMinScore": settings.triage_min_score,
            "analystName": settings.analyst_name or None}


def _require_agent() -> None:
    status = fetch_agent_status()
    if not status["configured"]:
        raise ApiError(503, status["reason"] or "The agent is off.")


@router.post("/risks/{risk_id}/{task}", status_code=202)
def start_risk_task(risk_id: str, task: Literal["intake", "scenario", "vectors", "evidence", "estimates"],
                    session: Session = Depends(get_session)) -> dict:
    """Start an agent task for one risk and return its run ID; the UI polls.

    - `intake` re-runs the quality check, triage and classification, even if
      the entry hasn't changed.
    - `scenario` drafts the default scenario (the risk must be ready and qualify).
    - `vectors` drafts attack vectors or failure paths from the approved scenario.
    - `evidence` gathers cited evidence and raises data requests (needs an
      approved scenario).
    - `estimates` drafts first-pass ranges from the evidence (needs an
      approved scenario and an evidence run).
    """
    row = get_risk(session, risk_id)
    _require_agent()
    if task == "intake":
        if agent_pipeline.is_busy(session, row.id):
            raise ApiError(409, "Checks are already running for this risk.")
        agent_pipeline.queue_intake(session, [row], force=True)
        run = agent_pipeline.latest_run(session, row.id, "quality")
        return {"runId": run.id if run else None, "riskId": row.risk_id}
    try:
        run_id = agent_pipeline.queue_risk_task(session, row, task)
    except agent_pipeline.TaskBlocked as exc:
        raise ApiError(409, str(exc)) from exc
    return {"runId": run_id, "riskId": row.risk_id}


@router.post("/register/intake", status_code=202)
def start_register_intake(session: Session = Depends(get_session)) -> dict:
    """Run the intake checks for every risk that hasn't been checked on its
    current entry (new risks, changed risks, and failed checks)."""
    _require_agent()
    rows = session.scalars(select(RiskRow).options(selectinload(RiskRow.monitoring))).all()
    return queue_checks(session, list(rows))


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(AgentRunRow, run_id)
    if run is None:
        raise ApiError(404, "Agent run not found.")
    risk = session.get(RiskRow, run.risk_pk) if run.risk_pk else None
    return {**run_out(run), "riskId": risk.risk_id if risk else None, "analysisId": run.analysis_id}


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
