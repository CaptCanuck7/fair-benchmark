"""The decision record: one append-only row per analyst action on a risk
(UI_REBUILD.md stage 1)."""

from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import DecisionLogRow

# Draft kinds and the step each belongs to.
DRAFT_STEP = {"quality": "quality", "triage": "triage", "classification": "classification",
              "scenario": "scenario", "vectors": "vectors", "estimate": "estimate", "report": "analysis"}

REASON_MIN = 10
RATIONALE_MIN = 15
REASON_MESSAGE = "Say why, in a sentence. It is kept with the decision record."


def log(session: Session, risk_pk: int, *, at: str, by: str, step: str, action: str,
        subject: str | None = None, reason: str | None = None, detail: dict[str, Any] | None = None) -> None:
    """Add a row. The caller commits it with the change it records."""
    session.add(DecisionLogRow(risk_pk=risk_pk, at=at, by=by, step=step, subject=subject, action=action,
                               reason=(reason or "").strip() or None, detail=detail))


def rows_out(session: Session, risk_pk: int) -> list[dict]:
    rows = session.scalars(select(DecisionLogRow).where(DecisionLogRow.risk_pk == risk_pk)
                           .order_by(DecisionLogRow.at, DecisionLogRow.id)).all()
    return [{"id": r.id, "at": r.at, "by": r.by, "step": r.step, "subject": r.subject, "action": r.action,
             "reason": r.reason, "detail": r.detail} for r in rows]


@event.listens_for(DecisionLogRow, "before_update")
def _no_update(*_args) -> None:
    raise RuntimeError("The decision log is append-only: rows can’t be changed.")


@event.listens_for(DecisionLogRow, "before_delete")
def _no_delete(*_args) -> None:
    raise RuntimeError("The decision log is append-only: rows can’t be deleted.")
