"""Answering data requests (AGENT_BUILD.md section 7). An answer becomes an
internal evidence item cited as "Data request answered by {team} on {date}"."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.models import DataRequestRow, EvidenceItemRow, RiskRow
from app.routers.register import reviewer_name, risk_detail_out
from app.schemas import now_iso

router = APIRouter(prefix="/api/data-requests", tags=["data-requests"])


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


@router.put("/{request_id}")
def answer_request(request_id: int, body: Answer, session: Session = Depends(get_session)) -> dict:
    """Record an answer. Answering again replaces the earlier answer and its evidence item."""
    req = session.get(DataRequestRow, request_id)
    if req is None:
        raise ApiError(404, "Data request not found.")
    answer = body.answer.strip()
    if not answer:
        raise ApiError(422, "Write the answer.", [{"path": "answer", "message": "Required."}])
    at = now_iso()
    req.answer, req.status, req.answered_by, req.answered_at = answer, "answered", reviewer_name(), at
    item = session.scalars(select(EvidenceItemRow).where(EvidenceItemRow.data_request_id == req.id)).first()
    if item is None:
        item = EvidenceItemRow(risk_pk=req.risk_pk, data_request_id=req.id, agent_run_id=None)
        session.add(item)
    item.origin, item.source_type = "internal", "data_request"
    item.source_name = f"{req.team} (data request)"
    item.citation = f"Data request answered by {req.team} on {at[:10]}"
    item.published_at, item.retrieved_at = at[:10], at
    item.summary = f"Q: {req.question} A: {answer}"[:2000]
    item.value, item.unit, item.factors, item.stale = None, None, [req.factor], False
    session.commit()
    return risk_detail_out(session, session.get(RiskRow, req.risk_pk))
