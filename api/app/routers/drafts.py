"""Reviewing agent drafts: approve, edit or reject (AGENT_BUILD.md section 10)."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import decision_log
from app.db import get_session
from app.errors import ApiError
from app.models import DraftRow, RiskRow
from app.register.drafts import EDITABLE, NOT_ALLOWED, Action, EditError, validate_edit
from app.routers.register import reviewer_name, risk_detail_out
from app.schemas import now_iso

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


class Review(BaseModel):
    action: Action
    # The analyst's version, for action "edit".
    payload: dict[str, Any] | None = None
    # Why: required for edit and reject, optional for approve. Kept in the decision log.
    reason: str | None = Field(default=None, max_length=2000)


@router.put("/{draft_id}")
def review_draft(draft_id: int, body: Review, session: Session = Depends(get_session)) -> dict:
    """Approve, edit or reject a draft. Returns the updated risk.

    An edit is stored beside the agent's version, which is never overwritten.
    A later review can change an earlier one (for example, approve a draft
    that was rejected)."""
    draft = session.get(DraftRow, draft_id)
    if draft is None:
        raise ApiError(404, "Draft not found.")
    if (draft.kind, body.action) in NOT_ALLOWED:
        raise ApiError(409, NOT_ALLOWED[(draft.kind, body.action)])
    reason = (body.reason or "").strip()
    if body.action in ("edit", "reject") and len(reason) < decision_log.REASON_MIN:
        raise ApiError(422, decision_log.REASON_MESSAGE, [{"path": "reason", "message": decision_log.REASON_MESSAGE}])
    before = draft.effective
    if body.action == "edit":
        if draft.kind not in EDITABLE:
            raise ApiError(409, f"A {draft.kind} draft can’t be edited.")
        if body.payload is None:
            raise ApiError(422, "Send the edited draft as payload.", [{"path": "payload", "message": "Required."}])
        try:
            draft.edited_payload = validate_edit(draft.kind, draft.payload, body.payload)
        except EditError as exc:
            raise ApiError(422, str(exc), [{"path": f"payload.{e['path']}", "message": e["message"]}
                                           for e in exc.errors]) from exc
        draft.status = "edited"
    elif body.action == "approve":
        # Approve accepts the version shown: the analyst's edit if there is one.
        draft.status = "edited" if draft.edited_payload is not None else "approved"
    else:
        # A rejected draft keeps any edit on record; downstream steps ignore it.
        draft.status = "rejected"
    draft.reviewer, draft.reviewed_at = reviewer_name(), now_iso()
    detail: dict[str, Any] = {"draftId": draft.id, "kind": draft.kind, "status": draft.status}
    if body.action == "edit":
        # Which top-level fields the edit changed, for the decision record.
        detail["changed"] = sorted(k for k in set(before) | set(draft.edited_payload or {})
                                   if k != "basedOn" and before.get(k) != (draft.edited_payload or {}).get(k))
    decision_log.log(session, draft.risk_pk, at=draft.reviewed_at, by=draft.reviewer,
                     step=decision_log.DRAFT_STEP.get(draft.kind, draft.kind), subject=str(draft.id),
                     action=body.action, reason=reason, detail=detail)
    session.commit()
    return risk_detail_out(session, session.get(RiskRow, draft.risk_pk))
