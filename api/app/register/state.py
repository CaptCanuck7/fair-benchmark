"""What a risk has reached in the pipeline: its latest drafts and run state.

Shared by the register router (to show it) and the pipeline (to decide what
may run next). A rejected draft counts as absent: nothing downstream uses it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentRunRow, DraftRow

ACTIVE = ("queued", "running")
INTAKE = ("quality", "triage", "classification")
KINDS = INTAKE + ("scenario", "vectors")


class IntakeState:
    """The latest draft of each kind and the run state for one risk."""

    def __init__(self, drafts: dict[str, DraftRow], busy: bool, last_run: AgentRunRow | None):
        self.drafts, self.busy, self.last_run = drafts, busy, last_run

    def get(self, kind: str, include_rejected: bool = False) -> dict | None:
        """The latest draft of `kind` as downstream steps see it; None if absent
        or rejected (unless `include_rejected`, for showing it)."""
        d = self.drafts.get(kind)
        if d is None or (d.status == "rejected" and not include_rejected):
            return None
        return d.effective


def intake_states(session: Session, risk_pks: list[int]) -> dict[int, IntakeState]:
    """Latest draft of each kind, and run state, per risk."""
    drafts: dict[int, dict[str, DraftRow]] = {pk: {} for pk in risk_pks}
    for d in session.scalars(select(DraftRow).where(DraftRow.risk_pk.in_(risk_pks),
                                                   DraftRow.kind.in_(KINDS)).order_by(DraftRow.id)):
        drafts[d.risk_pk][d.kind] = d
    runs: dict[int, list[AgentRunRow]] = {pk: [] for pk in risk_pks}
    for r in session.scalars(select(AgentRunRow).where(AgentRunRow.risk_pk.in_(risk_pks))
                             .order_by(AgentRunRow.started_at, AgentRunRow.id)):
        runs[r.risk_pk].append(r)
    return {
        pk: IntakeState(drafts[pk], any(r.status in ACTIVE for r in runs[pk]),
                        runs[pk][-1] if runs[pk] else None)
        for pk in risk_pks
    }


def current_stages(state: IntakeState, include_rejected: bool = False) -> tuple[dict | None, dict | None, dict | None]:
    """Quality, triage and classification results, counting only the stages the
    pipeline reached for the current quality result."""
    quality, triage, classification = (state.get(k, include_rejected) for k in INTAKE)
    if not quality or quality["status"] != "ready":
        triage = classification = None
    elif not triage or triage["status"] != "qualifies":
        classification = None
    return quality, triage, classification


def task_blocker(state: IntakeState, task: str) -> str | None:
    """Why a scenario or vectors task can't run for this risk yet, or None."""
    quality, triage, _ = current_stages(state)
    if not quality or quality["status"] != "ready":
        return "The quality check must find this entry ready first."
    if not triage or triage["status"] != "qualifies":
        return "Only risks that qualify in triage get a scenario. You can override triage, with a reason."
    if task in ("vectors", "evidence"):
        scenario = state.drafts.get("scenario")
        what = "Vectors are built" if task == "vectors" else "Evidence is gathered"
        if scenario is None:
            return "Draft and approve the scenario first."
        if scenario.status not in ("approved", "edited"):
            return f"Approve or edit the scenario first. {what} from the approved scenario."
    return None
