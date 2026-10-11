"""Task 7 for the workspace: input review and report drafts (AGENT_BUILD.md section 9.7)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import analysis_agent
from app.db import get_session
from app.errors import ApiError
from app.models import AgentRunRow, AnalysisDraftRow, RunRow
from app.report_check import unmatched_numbers
from app.routers import agent as agent_router
from app.routers.analyses import get_row
from app.routers.register import reviewer_name, run_out
from app.schemas import Analysis, input_hash, now_iso

router = APIRouter(prefix="/api", tags=["analysis agent"])


def _start(session: Session, analysis_id: str, task: str, run_id: str | None = None) -> dict:
    agent_router._require_agent()
    try:
        agent_run_id = analysis_agent.queue(session, analysis_id, task, run_id)
    except analysis_agent.AnalysisBusy as exc:
        raise ApiError(409, str(exc)) from exc
    return {"runId": agent_run_id, "analysisId": analysis_id}


@router.post("/agent/analyses/{analysis_id}/review", status_code=202)
def start_review(analysis_id: str, session: Session = Depends(get_session)) -> dict:
    """Review the saved analysis. Findings are advisory and never block a run."""
    get_row(session, analysis_id)
    return _start(session, analysis_id, "review")


@router.post("/agent/analyses/{analysis_id}/runs/{run_id}/report", status_code=202)
def start_report(analysis_id: str, run_id: str, session: Session = Depends(get_session)) -> dict:
    """Draft a leadership summary and, with a treatment, an exception
    justification from one stored run."""
    get_row(session, analysis_id)
    run = session.get(RunRow, run_id)
    if run is None or run.analysis_id != analysis_id:
        raise ApiError(404, "Run not found.")
    return _start(session, analysis_id, "report", run_id)


def draft_out(session: Session, d: AnalysisDraftRow, current_hash: str | None) -> dict:
    run = session.get(AgentRunRow, d.agent_run_id) if d.agent_run_id else None
    out = {
        "id": d.id, "kind": d.kind, "status": d.status, "payload": d.payload, "editedPayload": d.edited_payload,
        "effective": d.effective, "reviewer": d.reviewer, "reviewedAt": d.reviewed_at, "runId": d.run_id,
        "agentRunId": d.agent_run_id, "draftedAt": d.created_at, "model": run.model if run else None,
        "promptVersion": run.prompt_version if run else None,
    }
    if d.kind == "review":
        out["stale"] = current_hash is not None and d.input_hash != current_hash
    else:
        sim = session.get(RunRow, d.run_id)
        eff = d.effective
        # The agent's text passed the check when it was drafted; an edit is
        # checked too, and any mismatch is shown, not blocked.
        out["numberCheck"] = unmatched_numbers(
            [eff.get("leadershipSummary"), eff.get("exceptionJustification")], sim.results, sim.document_snapshot,
            analysis_agent.report_names(sim)) if sim else []
    return out


def agent_view(session: Session, analysis_id: str) -> dict:
    row = get_row(session, analysis_id)
    current = input_hash(Analysis.model_validate(row.document))
    drafts = session.scalars(select(AnalysisDraftRow).where(AnalysisDraftRow.analysis_id == analysis_id)
                             .order_by(AnalysisDraftRow.id.desc())).all()
    review = next((d for d in drafts if d.kind == "review"), None)
    reports: dict[str, dict] = {}
    for d in drafts:
        if d.kind == "report" and d.run_id not in reports:
            reports[d.run_id] = draft_out(session, d, current)
    runs = session.scalars(select(AgentRunRow).where(AgentRunRow.analysis_id == analysis_id)
                           .order_by(AgentRunRow.started_at.desc()).limit(10)).all()
    return {
        "busy": any(r.status in analysis_agent.ACTIVE for r in runs),
        "runs": [run_out(r) for r in runs],
        "review": draft_out(session, review, current) if review else None,
        "reports": reports,
    }


@router.get("/analyses/{analysis_id}/agent")
def get_agent_view(analysis_id: str, session: Session = Depends(get_session)) -> dict:
    """The latest input review, the latest report per run, and recent agent runs."""
    return agent_view(session, analysis_id)


class ReportEdit(BaseModel):
    leadershipSummary: str = Field(min_length=1, max_length=6000)
    exceptionJustification: str | None = Field(default=None, max_length=6000)


class DraftReview(BaseModel):
    action: Literal["approve", "edit", "reject"]
    payload: ReportEdit | None = None


@router.put("/analysis-drafts/{draft_id}")
def review_analysis_draft(draft_id: int, body: DraftReview, session: Session = Depends(get_session)) -> dict:
    """Approve, edit (reports only) or reject. Returns the analysis's agent view."""
    d = session.get(AnalysisDraftRow, draft_id)
    if d is None:
        raise ApiError(404, "Draft not found.")
    if body.action == "edit":
        if d.kind != "report":
            raise ApiError(409, "Review findings can’t be edited. Approve or reject them.")
        if body.payload is None:
            raise ApiError(422, "Send the edited report as payload.", [{"path": "payload", "message": "Required."}])
        d.edited_payload = {**d.payload, **body.payload.model_dump()}
        d.status = "edited"
    elif body.action == "approve":
        d.status = "edited" if d.edited_payload is not None else "approved"
    else:
        d.status = "rejected"
    d.reviewer, d.reviewed_at = reviewer_name(), now_iso()
    session.commit()
    return agent_view(session, d.analysis_id)
