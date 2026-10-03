"""Analyses: list, create, fetch, replace, delete, duplicate."""

from typing import Any

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.models import AnalysisRow, RunRow
from app.schemas import Analysis, dump, input_hash, new_id, now_iso

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

HASH_HEADER = "X-Input-Hash"


def get_row(session: Session, analysis_id: str) -> AnalysisRow:
    row = session.get(AnalysisRow, analysis_id)
    if row is None:
        raise ApiError(404, "Analysis not found.")
    return row


def doc_response(response: Response, analysis: Analysis) -> dict:
    """Return the document, with its input hash in a header for the stale check."""
    response.headers[HASH_HEADER] = input_hash(analysis)
    return dump(analysis)


def save_new(session: Session, analysis: Analysis) -> AnalysisRow:
    """Store an analysis under a fresh id with fresh timestamps."""
    t = now_iso()
    analysis.id, analysis.created_at, analysis.updated_at = new_id(), t, t
    analysis.summary = None
    row = AnalysisRow(id=analysis.id, title=analysis.title, document=dump(analysis), created_at=t, updated_at=t)
    session.add(row)
    session.commit()
    return row


def latest_run(session: Session, analysis_id: str) -> RunRow | None:
    stmt = select(RunRow).where(RunRow.analysis_id == analysis_id).order_by(RunRow.run_at.desc()).limit(1)
    return session.scalars(stmt).first()


def latest_run_summary(session: Session, analysis_id: str) -> dict | None:
    run = latest_run(session, analysis_id)
    if run is None:
        return None
    return {
        "id": run.id,
        "runAt": run.run_at,
        "inputHash": run.input_hash,
        "options": [
            {"stateId": s["stateId"], "name": s["name"], "meanAnnualLoss": s["meanAnnualLoss"]}
            for s in run.results["states"]
        ],
    }


@router.get("")
def list_analyses(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(AnalysisRow).order_by(AnalysisRow.updated_at.desc())).all()
    out = []
    for row in rows:
        doc = Analysis.model_validate(row.document)
        current = input_hash(doc)
        latest = latest_run_summary(session, row.id)
        if latest:
            latest["stale"] = latest["inputHash"] != current
        out.append({
            "id": row.id,
            "title": row.title,
            "states": len(doc.states),
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
            "inputHash": current,
            "latestRun": latest,
        })
    return out


@router.post("", status_code=201)
def create_analysis(response: Response, body: dict[str, Any] | None = Body(None),
                    session: Session = Depends(get_session)) -> dict:
    analysis = Analysis.model_validate(body or {})
    save_new(session, analysis)
    return doc_response(response, analysis)


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str, response: Response, session: Session = Depends(get_session)) -> dict:
    row = get_row(session, analysis_id)
    return doc_response(response, Analysis.model_validate(row.document))


@router.put("/{analysis_id}")
def replace_analysis(analysis_id: str, analysis: Analysis, response: Response,
                     session: Session = Depends(get_session)) -> dict:
    row = get_row(session, analysis_id)
    analysis.id = analysis_id
    analysis.created_at = row.created_at
    analysis.updated_at = now_iso()
    analysis.summary = None
    row.title = analysis.title
    row.document = dump(analysis)
    row.updated_at = analysis.updated_at
    session.commit()
    return doc_response(response, analysis)


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, session: Session = Depends(get_session)) -> Response:
    session.delete(get_row(session, analysis_id))
    session.commit()
    return Response(status_code=204)


@router.post("/{analysis_id}/duplicate", status_code=201)
def duplicate_analysis(analysis_id: str, response: Response, session: Session = Depends(get_session)) -> dict:
    analysis = Analysis.model_validate(get_row(session, analysis_id).document)
    analysis.title = f"{analysis.title} (copy)"
    save_new(session, analysis)
    return doc_response(response, analysis)
