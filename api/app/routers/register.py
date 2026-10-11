"""The tactical risk register: import a workbook, list risks, show one risk,
and override triage. Importing queues the intake checks (quality, triage,
classification) when the agent is configured."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import agent_pipeline
from app.register.drafts import usable
from app.register.state import IntakeState, current_stages, intake_states, task_blocker
from app.agent_client import fetch_agent_status
from app.config import settings
from app.db import get_session
from app.errors import ApiError
from app.models import (
    AgentRunRow,
    DataRequestRow,
    DraftRow,
    EvidenceItemRow,
    EvidenceRunRow,
    RegisterImportRow,
    RiskLinkRow,
    RiskMonitoringRow,
    RiskRow,
)
from app.register.parser import ParsedRegister, parse_workbook
from app.schemas import new_id, now_iso
from app.xlsx import WorkbookError

router = APIRouter(prefix="/api/register", tags=["register"])

IMPORT_PATH = "/api/register/import"


def store_register(session: Session, filename: str, parsed: ParsedRegister) -> dict:
    """Save an import. A risk ID already in the database is updated in place, so
    anything linked to it (drafts, evidence, analyses) stays linked."""
    imp = RegisterImportRow(id=new_id(), filename=filename, imported_at=now_iso(),
                            row_count=parsed.row_count, risk_count=len(parsed.risks))
    session.add(imp)
    existing = {r.risk_id: r for r in session.scalars(
        select(RiskRow).where(RiskRow.risk_id.in_([p.risk_id for p in parsed.risks]))
    )}
    created = updated = 0
    for p in parsed.risks:
        row = existing.get(p.risk_id)
        if row is None:
            row = RiskRow(risk_id=p.risk_id)
            session.add(row)
            created += 1
        else:
            updated += 1
        row.import_id = imp.id
        row.fields, row.sections, row.structured = p.fields, p.sections, p.structured
        row.baseline_score, row.target_score, row.residual_score = p.baseline_score, p.target_score, p.residual_score
        row.monitoring = [
            RiskMonitoringRow(
                task_name=m["task_name"], update_text=m["update_text"],
                residual_impact=m["residual_impact"], residual_likelihood=m["residual_likelihood"],
                completed_date=m["completed_date"],
            )
            for m in p.monitoring
        ]
    session.commit()
    return {
        "importId": imp.id, "filename": filename, "importedAt": imp.imported_at,
        "rowCount": imp.row_count, "riskCount": imp.risk_count, "created": created, "updated": updated,
    }


@router.post("/import", status_code=201)
async def import_register(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    filename = (file.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not filename.lower().endswith(".xlsx"):
        raise ApiError(422, "Choose an Excel .xlsx workbook. Other file types aren’t accepted.")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "The workbook is larger than the 5 MB limit.")
    try:
        parsed = parse_workbook(data)
    except WorkbookError as exc:
        raise ApiError(422, str(exc), [{"path": "file", "message": str(exc)}]) from exc
    if not parsed.risks:
        raise ApiError(422, "The register has no risk rows.")
    result = store_register(session, filename, parsed)
    rows = session.scalars(select(RiskRow).where(RiskRow.import_id == result["importId"])).all()
    return {**result, "checks": queue_checks(session, list(rows))}


def queue_checks(session: Session, rows: list[RiskRow], force: bool = False) -> dict:
    """Queue the intake checks if the agent is on. Says why not if it's off."""
    status = fetch_agent_status()
    if not status["configured"]:
        return {"queued": [], "agentOff": status["reason"]}
    return {"queued": agent_pipeline.queue_intake(session, rows, force=force), "agentOff": None}


@router.get("/imports")
def list_imports(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(RegisterImportRow).order_by(RegisterImportRow.imported_at.desc())).all()
    return [{"importId": r.id, "filename": r.filename, "importedAt": r.imported_at,
             "rowCount": r.row_count, "riskCount": r.risk_count} for r in rows]


FIELD_LABELS = {
    "assets": "assets", "environment": "environment", "risk_owner": "risk owner",
    "baseline_impact": "impact", "baseline_likelihood": "likelihood", "risk_action": "risk action",
    "risk_statement": "risk statement", "risk_analysis": "a clearer analysis",
    "detailed_analysis": "a detailed analysis", "baseline_controls": "baseline controls",
    "exploit_paths": "exploit paths", "mitigation_plan": "a mitigation plan",
    "agent:asset": "a named asset", "agent:condition": "a clear condition", "agent:loss_path": "how loss could happen",
}


def _note(quality: dict | None, triage: dict | None) -> str | None:
    """Why a risk stopped: the gaps for needs_info, the reason for screened out."""
    if quality and quality["status"] == "needs_info":
        # Rule gaps and blocking checks; the model's own comments stay on the detail page.
        fields = [g["field"] for g in quality["gaps"] if g["source"] == "rule"] + \
            [b for b in quality.get("blockedBy", []) if b.startswith("agent:")]
        labels = list(dict.fromkeys(FIELD_LABELS.get(f, f.replace("_", " ")) for f in fields))
        return "Needs " + ", ".join(labels) + "."
    if triage and triage["status"] == "screened_out":
        override = triage.get("override")
        if override:
            return f"Screened out by {override['by']}: {override['reason']}"
        return triage.get("reason") or triage["rule"]
    return None


def risk_summary(row: RiskRow, state: IntakeState | None = None, analysis_id: str | None = None) -> dict:
    f = row.fields
    state = state or IntakeState({}, False, None)
    quality, triage, classification = current_stages(state)
    last = state.last_run
    return {
        "riskId": row.risk_id,
        "title": f.get("risk_title"),
        "category": f.get("risk_category"),
        "assetIds": f.get("asset_ids", []),
        "baselineImpact": f.get("baseline_impact"),
        "baselineLikelihood": f.get("baseline_likelihood"),
        "baselineScore": row.baseline_score,
        "targetScore": row.target_score,
        "residualScore": row.residual_score,
        "structured": row.structured,
        "monitoringCount": len(row.monitoring),
        # Null means "not run yet", or not reached: needs_info stops before triage.
        "quality": quality["status"] if quality else None,
        "triage": triage["status"] if triage else None,
        "triageOverridden": bool(triage and triage.get("override")),
        "classification": classification["primary_type"] if classification else None,
        "secondaryClassification": classification.get("secondary_type") if classification else None,
        "note": _note(quality, triage),
        "agent": {
            "state": "running" if state.busy else ("failed" if last and last.status == "failed" else None),
            "error": last.error if last and last.status == "failed" and not state.busy else None,
        },
        # The latest analysis created from this risk.
        "analysisId": analysis_id,
    }


def _natural_key(risk_id: str) -> list:
    """TR-6 before TR-10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", risk_id)]


@router.get("/risks")
def list_risks(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(RiskRow).options(selectinload(RiskRow.monitoring))).all()
    states = intake_states(session, [r.id for r in rows])
    links = analysis_links(session, [r.id for r in rows])
    return [risk_summary(r, states[r.id], links.get(r.id)) for r in sorted(rows, key=lambda r: _natural_key(r.risk_id))]


def get_risk(session: Session, risk_id: str) -> RiskRow:
    row = session.scalars(select(RiskRow).where(RiskRow.risk_id == risk_id)).first()
    if row is None:
        raise ApiError(404, "Risk not found.")
    return row


def run_out(run: AgentRunRow) -> dict:
    return {
        "id": run.id, "task": run.task, "status": run.status, "model": run.model,
        "promptVersion": run.prompt_version, "inputHash": run.input_hash,
        "inputTokens": run.input_tokens, "outputTokens": run.output_tokens,
        "startedAt": run.started_at, "finishedAt": run.finished_at, "error": run.error,
    }


def draft_out(d: DraftRow, runs: dict[str, AgentRunRow]) -> dict:
    run = runs.get(d.agent_run_id or "")
    return {
        "id": d.id, "kind": d.kind, "status": d.status, "payload": d.payload, "editedPayload": d.edited_payload,
        "effective": d.effective, "reviewer": d.reviewer, "reviewedAt": d.reviewed_at,
        "agentRunId": d.agent_run_id, "draftedAt": run.finished_at if run else None,
        "model": run.model if run else None, "promptVersion": run.prompt_version if run else None,
    }


def vectors_stale(state: IntakeState) -> bool:
    """True when the vectors were built from a scenario that has since changed."""
    vectors, scenario = state.drafts.get("vectors"), state.drafts.get("scenario")
    if vectors is None:
        return False
    based = (vectors.payload or {}).get("basedOn") or {}
    current = usable(scenario)
    if current is None:
        return True
    current = {k: v for k, v in current.items() if k != "basedOn"}
    return based.get("scenarioDraftId") != scenario.id or         based.get("scenarioHash") != agent_pipeline.scenario_hash(current)


FACTOR_GROUPS = {
    "frequency": ("lef", "tef", "cf", "poa"),
    "susceptibility": ("vuln", "tcap", "rs"),
    "primary": ("primary.productivity", "primary.response", "primary.replacement"),
    "secondary": ("slef", "secondary.response", "secondary.fines", "secondary.competitive", "secondary.reputation"),
}


def evidence_item_out(e: EvidenceItemRow) -> dict:
    return {
        "id": e.id, "origin": e.origin, "sourceType": e.source_type, "sourceName": e.source_name,
        "citation": e.citation, "publishedAt": e.published_at, "retrievedAt": e.retrieved_at, "summary": e.summary,
        "value": e.value, "unit": e.unit, "factors": e.factors, "stale": e.stale,
        "groups": [g for g, keys in FACTOR_GROUPS.items() if any(f in keys for f in e.factors)],
        "fromDataRequest": e.data_request_id,
    }


def data_request_out(r: DataRequestRow) -> dict:
    return {
        "id": r.id, "team": r.team, "question": r.question, "factor": r.factor, "reason": r.reason,
        "status": r.status, "answer": r.answer, "answeredBy": r.answered_by, "answeredAt": r.answered_at,
        "groups": [g for g, keys in FACTOR_GROUPS.items() if r.factor in keys],
    }


def evidence_out(session: Session, row: RiskRow) -> dict:
    """The latest evidence run's items and data requests, plus every answered
    request (answers outlive a re-run) and the evidence each answer created."""
    items, requests = agent_pipeline.current_evidence(session, row.id)
    latest = agent_pipeline.latest_evidence_run(session, row.id)
    summary = session.get(EvidenceRunRow, latest.id) if latest else None
    return {
        "evidence": [evidence_item_out(e) for e in items],
        "dataRequests": [data_request_out(r) for r in requests],
        "evidenceRun": None if latest is None else {
            "id": latest.id, "finishedAt": latest.finished_at, "model": latest.model,
            "toolCalls": summary.tool_calls if summary else None,
            "rejected": summary.rejected if summary else [],
            "notes": summary.notes if summary else {},
        },
    }


def analysis_links(session: Session, risk_pks: list[int]) -> dict[int, str]:
    """The latest analysis created from each risk."""
    out: dict[int, str] = {}
    for link in session.scalars(select(RiskLinkRow).where(RiskLinkRow.risk_pk.in_(risk_pks)).order_by(RiskLinkRow.id)):
        out[link.risk_pk] = link.analysis_id
    return out


def risk_detail_out(session: Session, row: RiskRow) -> dict:
    imp = session.get(RegisterImportRow, row.import_id)
    state = intake_states(session, [row.id])[row.id]
    runs = session.scalars(select(AgentRunRow).where(AgentRunRow.risk_pk == row.id)
                           .order_by(AgentRunRow.started_at.desc(), AgentRunRow.id.desc())).all()
    by_id = {r.id: r for r in runs}
    drafts = session.scalars(select(DraftRow).where(DraftRow.risk_pk == row.id).order_by(DraftRow.id.desc())).all()
    # Rejected drafts are shown (so the analyst can see and reverse them) but not used downstream.
    reached = dict(zip(agent_pipeline.TASKS, current_stages(state, include_rejected=True)))
    gate = agent_pipeline.evidence_gate(session, row.id)
    from app.routers.estimates import estimates_out  # imported here: that module imports this one

    return {
        **risk_summary(row, state, analysis_links(session, [row.id]).get(row.id)),
        "fields": row.fields,
        "sections": row.sections,
        "monitoring": [
            {
                "taskName": m.task_name, "updateText": m.update_text,
                "residualImpact": m.residual_impact, "residualLikelihood": m.residual_likelihood,
                "residualScore": (m.residual_impact * m.residual_likelihood
                                  if m.residual_impact and m.residual_likelihood else None),
                "completedDate": m.completed_date,
            }
            for m in row.monitoring
        ],
        "import": {"importId": imp.id, "filename": imp.filename, "importedAt": imp.imported_at} if imp else None,
        # The current intake results: only the stages the pipeline reached.
        "intake": {kind: draft_out(state.drafts[kind], by_id) if reached[kind] is not None else None
                   for kind in agent_pipeline.TASKS},
        "scenario": draft_out(state.drafts["scenario"], by_id) if "scenario" in state.drafts else None,
        "vectors": draft_out(state.drafts["vectors"], by_id) if "vectors" in state.drafts else None,
        "vectorsStale": vectors_stale(state),
        # Why each analyst-started task can't run yet (null when it can).
        "blocked": {task: task_blocker(state, task, *gate) for task in agent_pipeline.RISK_TASKS},
        # Estimate ranges stay hidden until revealed, factor by factor.
        "estimates": estimates_out(session, row),
        "triageThreshold": settings.triage_min_score,
        # Estimate drafts are left out: their ranges stay hidden until revealed.
        "drafts": [draft_out(d, by_id) for d in drafts if d.kind != "estimate"],
        "runs": [run_out(r) for r in runs[:30]],
        **evidence_out(session, row),
    }


@router.get("/risks/{risk_id}")
def risk_detail(risk_id: str, session: Session = Depends(get_session)) -> dict:
    return risk_detail_out(session, get_risk(session, risk_id))


def reviewer_name() -> str:
    return settings.analyst_name or "Analyst (name not set)"


class TriageOverride(BaseModel):
    status: Literal["qualifies", "screened_out"]
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/risks/{risk_id}/triage-override")
def triage_override(risk_id: str, body: TriageOverride, session: Session = Depends(get_session)) -> dict:
    """Override the triage rule either way, with a recorded reason (section 9.2)."""
    row = get_risk(session, risk_id)
    reason = body.reason.strip()
    if len(reason) < 3:
        raise ApiError(422, "Give a reason for the override.", [{"path": "reason", "message": "Give a reason."}])
    state = intake_states(session, [row.id])[row.id]
    if current_stages(state)[1] is None:
        raise ApiError(409, "This risk hasn’t been triaged, so there is nothing to override. "
                            "Triage runs once the quality check finds the entry ready.")
    if state.busy:
        raise ApiError(409, "Checks are still running for this risk. Try again when they finish.")
    draft = state.drafts["triage"]
    at = now_iso()
    draft.edited_payload = {**draft.payload, "status": body.status,
                            "override": {"from": draft.payload["status"], "reason": reason,
                                         "by": reviewer_name(), "at": at}}
    draft.status, draft.reviewer, draft.reviewed_at = "edited", reviewer_name(), at
    session.commit()

    # A risk overridden into the pipeline is classified next, as if it had qualified.
    classification_note = None
    if body.status == "qualifies" and "classification" not in state.drafts:
        status = fetch_agent_status()
        if status["configured"]:
            agent_pipeline.queue_classification(session, row)
        else:
            classification_note = status["reason"]
    return {**risk_detail_out(session, row), "classificationNote": classification_note}
