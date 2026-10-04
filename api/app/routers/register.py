"""The tactical risk register: import a workbook, list risks, show one risk."""

import re

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_session
from app.errors import ApiError
from app.models import RegisterImportRow, RiskMonitoringRow, RiskRow
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
    return store_register(session, filename, parsed)


@router.get("/imports")
def list_imports(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(RegisterImportRow).order_by(RegisterImportRow.imported_at.desc())).all()
    return [{"importId": r.id, "filename": r.filename, "importedAt": r.imported_at,
             "rowCount": r.row_count, "riskCount": r.risk_count} for r in rows]


def risk_summary(row: RiskRow) -> dict:
    f = row.fields
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
        # Filled in by the agent milestones; null means "not run yet".
        "quality": None,
        "triage": None,
        "classification": None,
        "analysisId": None,
    }


def _natural_key(risk_id: str) -> list:
    """TR-6 before TR-10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", risk_id)]


@router.get("/risks")
def list_risks(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(RiskRow).options(selectinload(RiskRow.monitoring))).all()
    return [risk_summary(r) for r in sorted(rows, key=lambda r: _natural_key(r.risk_id))]


def get_risk(session: Session, risk_id: str) -> RiskRow:
    row = session.scalars(select(RiskRow).where(RiskRow.risk_id == risk_id)).first()
    if row is None:
        raise ApiError(404, "Risk not found.")
    return row


@router.get("/risks/{risk_id}")
def risk_detail(risk_id: str, session: Session = Depends(get_session)) -> dict:
    row = get_risk(session, risk_id)
    imp = session.get(RegisterImportRow, row.import_id)
    return {
        **risk_summary(row),
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
        # Filled in by the agent milestones.
        "drafts": [],
        "evidence": [],
        "dataRequests": [],
    }
