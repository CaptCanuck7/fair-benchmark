"""Estimates, the anchoring guard, and push to analysis (AGENT_BUILD.md section 10).

The anchoring guard: an estimate draft's ranges are never sent to the browser
until the analyst reveals that factor. A reveal records whether the analyst had
entered a range of their own first. The analyst then keeps their range, takes
the agent's, or enters a third; that decision is what gets pushed.
"""

from typing import Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_pipeline
from app.content.factors import CONF, F
from app.db import get_session
from app.engine.distributions import dist_status
from app.errors import ApiError
from app.models import (
    DraftRow,
    EvidenceItemRow,
    EstimateRevealRow,
    FactorProvenanceRow,
    RiskLinkRow,
    RiskRow,
)
from app.register.drafts import usable
from app.register.state import intake_states
from app.routers.analyses import save_new
from app.routers.register import get_risk, reviewer_name, risk_detail_out
from app.schemas import Analysis, Dist, State, now_iso

router = APIRouter(prefix="/api", tags=["estimates"])

FACTOR_ORDER = list(F)  # analysis order: lef, tef, cf, poa, vuln, tcap, rs, primary.*, slef, secondary.*
FREQUENCY = {"lef": ["lef"], "tef_vuln": ["tef"], "cf_poa": ["cf", "poa"]}


def method_factors(method: dict) -> list[str]:
    """The factors an analysis built with this method uses: its frequency
    factors and every loss factor. Others would be pushed into rows the
    workspace hides, so the tab doesn't offer them."""
    freq = list(FREQUENCY[method["mode"]])
    if method["mode"] != "lef":
        freq += ["vuln"] if method["vuln_mode"] == "direct" else ["tcap", "rs"]
    loss = [k for k in FACTOR_ORDER if k.startswith(("primary.", "secondary.")) or k == "slef"]
    return [k for k in FACTOR_ORDER if k in freq or k in loss]


class RangeIn(BaseModel):
    min: float | None = None
    ml: float | None = None
    max: float | None = None
    conf: Literal["low", "med", "high"] = "med"


def latest_estimate(session: Session, risk_pk: int) -> DraftRow | None:
    return session.scalars(select(DraftRow).where(DraftRow.risk_pk == risk_pk, DraftRow.kind == "estimate")
                           .order_by(DraftRow.id.desc()).limit(1)).first()


def _reveals(session: Session, draft: DraftRow) -> dict[str, EstimateRevealRow]:
    rows = session.scalars(select(EstimateRevealRow).where(EstimateRevealRow.draft_id == draft.id)
                           .order_by(EstimateRevealRow.id)).all()
    return {r.factor: r for r in rows}


def _decisions(draft: DraftRow) -> dict[str, dict]:
    return dict((draft.edited_payload or {}).get("decisions") or {})


def range_status(factor: str, r: RangeIn | dict | None) -> tuple[str, str | None]:
    """The workbench's own range check (CLAUDE.md section 3) for this factor's kind."""
    if r is None:
        return "empty", None
    d = r if isinstance(r, RangeIn) else RangeIn.model_validate(r)
    return dist_status(Dist(min=d.min, ml=d.ml, max=d.max, conf=d.conf), F[factor]["kind"])


def estimates_out(session: Session, row: RiskRow) -> dict | None:
    """The estimates tab, with each agent range hidden until it is revealed."""
    draft = latest_estimate(session, row.id)
    if draft is None:
        return None
    payload = draft.payload
    reveals, decisions = _reveals(session, draft), _decisions(draft)
    by_factor = {e["factor"]: e for e in payload["estimates"]}
    unestimated = {u["factor"]: u for u in payload["unestimated"]}
    factors = []
    # Every factor the recommended method uses, so the analyst can enter a range
    # even where the agent said nothing.
    for key in method_factors(payload["method"]):
        rev = reveals.get(key)
        est = by_factor.get(key)
        factors.append({
            "factor": key,
            "status": "estimated" if est else "unestimated",  # unestimated may carry no reason
            "revealed": rev is not None,
            "agent": ({"min": est["min"], "ml": est["ml"], "max": est["max"], "conf": est["conf"],
                       "rationale": est["rationale"], "evidenceIds": est["evidence_ids"], "basis": est["basis"],
                       # direct or related; absent on drafts from before it was recorded.
                       **({"evidenceMatch": est["evidence_match"]} if "evidence_match" in est else {})}
                      if est and rev else None),
            "unestimated": ({"reason": unestimated[key]["reason"],
                             "dataRequestId": unestimated[key].get("data_request_id")} if key in unestimated else None),
            "reveal": ({"analystRange": rev.analyst_range, "enteredBeforeReveal": rev.entered_before_reveal,
                        "revealedAt": rev.revealed_at} if rev else None),
            "decision": decisions.get(key),
        })
    state = intake_states(session, [row.id])[row.id]
    return {"draftId": draft.id, "method": payload["method"], "factors": factors,
            "decided": sum(1 for f in factors if f["decision"]), "agentRunId": draft.agent_run_id,
            # What changed since these estimates were drafted.
            "stale": agent_pipeline.estimates_stale(session, row.id, draft, state)}


def _draft_or_409(session: Session, row: RiskRow) -> DraftRow:
    draft = latest_estimate(session, row.id)
    if draft is None:
        raise ApiError(409, "There are no estimates for this risk yet. Draft them on the Estimates tab.")
    return draft


def _valid_range(factor: str, r: RangeIn) -> RangeIn:
    status, msg = range_status(factor, r)
    if status != "ok":
        raise ApiError(422, msg or "Enter all three values: minimum, most likely and maximum.",
                       [{"path": "range", "message": msg or "Enter all three values."}])
    return r


class RevealIn(BaseModel):
    analystRange: RangeIn | None = None


@router.post("/register/risks/{risk_id}/estimates/{factor}/reveal")
def reveal(risk_id: str, factor: str, body: RevealIn, session: Session = Depends(get_session)) -> dict:
    """Show the agent's range for one factor, recording whether the analyst had
    entered a complete range of their own first."""
    row = get_risk(session, risk_id)
    draft = _draft_or_409(session, row)
    if factor not in {e["factor"] for e in draft.payload["estimates"]}:
        raise ApiError(409, "The agent proposed no range for this factor: it found no evidence for it.")
    if factor not in _reveals(session, draft):
        entered = body.analystRange
        status, _ = range_status(factor, entered)
        if status == "error":
            raise ApiError(422, "Your range isn’t valid yet. Fix it or clear it before revealing.",
                           [{"path": "analystRange", "message": "Invalid range."}])
        session.add(EstimateRevealRow(
            risk_pk=row.id, draft_id=draft.id, factor=factor, revealed_at=now_iso(),
            analyst_range=entered.model_dump() if status == "ok" else None, entered_before_reveal=status == "ok",
        ))
        session.commit()
    return risk_detail_out(session, row)


class DecisionIn(BaseModel):
    choice: Literal["agent", "analyst"]
    range: RangeIn | None = None


@router.put("/register/risks/{risk_id}/estimates/{factor}")
def decide(risk_id: str, factor: str, body: DecisionIn, session: Session = Depends(get_session)) -> dict:
    """Keep your range, take the agent's, or enter a third. Only decided
    factors are pushed to an analysis."""
    if factor not in F:
        raise ApiError(404, "Unknown factor.")
    row = get_risk(session, risk_id)
    draft = _draft_or_409(session, row)
    if factor not in method_factors(draft.payload["method"]):
        raise ApiError(409, "The recommended method doesn’t use this factor.")
    at, by = now_iso(), reviewer_name()
    if body.choice == "agent":
        est = next((e for e in draft.payload["estimates"] if e["factor"] == factor), None)
        if est is None:
            raise ApiError(409, "The agent proposed no range for this factor.")
        if factor not in _reveals(session, draft):
            raise ApiError(409, "Show the agent’s range before taking it.")
        decision = {"choice": "agent", "min": est["min"], "ml": est["ml"], "max": est["max"], "conf": est["conf"],
                    "rationale": est["rationale"], "evidenceIds": est["evidence_ids"], "by": by, "at": at,
                    **({"evidenceMatch": est["evidence_match"]} if "evidence_match" in est else {})}
    else:
        if body.range is None:
            raise ApiError(422, "Enter your range.", [{"path": "range", "message": "Required."}])
        r = _valid_range(factor, body.range)
        decision = {"choice": "analyst", "min": r.min, "ml": r.ml, "max": r.max, "conf": r.conf,
                    "rationale": None, "evidenceIds": [], "by": by, "at": at,
                    "revealedFirst": factor in _reveals(session, draft)}
    decisions = {**_decisions(draft), factor: decision}
    draft.edited_payload = {**draft.payload, "decisions": decisions}
    draft.status, draft.reviewer, draft.reviewed_at = "edited", by, at
    session.commit()
    return risk_detail_out(session, row)


@router.delete("/register/risks/{risk_id}/estimates/{factor}")
def clear_decision(risk_id: str, factor: str, session: Session = Depends(get_session)) -> dict:
    row = get_risk(session, risk_id)
    draft = _draft_or_409(session, row)
    decisions = _decisions(draft)
    decisions.pop(factor, None)
    draft.edited_payload = {**draft.payload, "decisions": decisions}
    draft.status = "edited" if decisions else "drafted"
    session.commit()
    return risk_detail_out(session, row)


# --- Push to analysis -------------------------------------------------------------

FACTOR_WORDS = {"frequency": "how often the threat acts", "susceptibility": "whether an attempt succeeds",
                "magnitude": "how much is lost"}


def _controls_text(scenario: dict) -> str:
    lines = []
    for c in scenario.get("controls", []):
        line = f"{c['control']} (affects {FACTOR_WORDS.get(c['factor'], c['factor'])})"
        if not c.get("helps"):
            line += f": doesn’t help in this scenario. {c.get('note') or ''}".rstrip()
        lines.append(line)
    return "\n".join(lines)


def _citations(session: Session, ids: list[int]) -> list[str]:
    if not ids:
        return []
    rows = session.scalars(select(EvidenceItemRow).where(EvidenceItemRow.id.in_(ids))).all()
    return [r.citation for r in rows]


def build_analysis(session: Session, row: RiskRow, scenario: dict, estimate: DraftRow | None) -> tuple[Analysis, list]:
    f = row.fields
    a = Analysis()
    a.title = f"{row.risk_id} {f.get('risk_title') or ''}".strip()
    a.scope.asset = scenario["asset"]
    a.scope.threat_community = scenario["threat_community"]
    a.scope.threat_type = scenario["threat_type"]
    a.scope.effect = scenario["effect"]
    a.scope.condition = scenario.get("condition", "")
    a.scope.controls = _controls_text(scenario)
    a.scope.notes = "\n".join([scenario.get("scenario_sentence", ""), *scenario.get("notes", []),
                               f"Created from register risk {row.risk_id} on {now_iso()[:10]}."]).strip()
    state = State(name="Current state")
    provenance = []
    if estimate is not None:
        method = estimate.payload["method"]
        state.lef.mode, state.lef.vuln_mode = method["mode"], method["vuln_mode"]
        used = method_factors(method)
        for key, d in _decisions(estimate).items():
            if key not in used:
                continue
            if d["choice"] == "agent":
                cites = _citations(session, d["evidenceIds"])
                related = ("\nRests on related evidence: no cited item is tagged to this factor."
                           if d.get("evidenceMatch") == "related" else "")
                src = (f"{d['rationale']}\nSources: {'; '.join(cites)}{related}\n"
                       f"Agent-drafted, approved by {d['by']} on {d['at'][:10]}.")
            else:
                src = f"Analyst estimate by {d['by']} on {d['at'][:10]}."
            dist = Dist(min=d["min"], ml=d["ml"], max=d["max"], conf=d["conf"] if d["conf"] in CONF else "med", src=src)
            obj = state
            parts = F[key]["path"].split(".")
            for p in parts[:-1]:
                obj = getattr(obj, p)
            setattr(obj, parts[-1], dist)
            provenance.append((key, d))
    a.states = [state]
    return a, provenance


class CreateIn(BaseModel):
    acknowledgeStale: bool = False


def stale_what(stale: dict[str, bool]) -> str | None:
    """'the scenario', 'the evidence', both, or None."""
    parts = [name for name in ("scenario", "evidence") if stale.get(name)]
    return " and ".join(f"the {p}" for p in parts) if parts else None


@router.post("/register/risks/{risk_id}/create-analysis", status_code=201)
def create_analysis(risk_id: str, body: CreateIn | None = Body(None), session: Session = Depends(get_session)) -> dict:
    """Build an analysis from the approved scenario and the decided ranges, and
    save it through the existing create path. Undecided factors stay empty; no
    treatment state is created. Estimates drafted before the scenario or the
    evidence changed need `acknowledgeStale`."""
    row = get_risk(session, risk_id)
    state = intake_states(session, [row.id])[row.id]
    scenario_draft = state.drafts.get("scenario")
    scenario = usable(scenario_draft)
    if scenario is None:
        raise ApiError(409, "Approve or edit the scenario first: it becomes the analysis scope.")
    estimate = latest_estimate(session, row.id)
    changed = stale_what(agent_pipeline.estimates_stale(session, row.id, estimate, state)) if estimate else None
    if changed and not (body and body.acknowledgeStale):
        raise ApiError(409, f"The estimates were drafted before {changed} changed. Draft them again, or create "
                            "the analysis anyway.")
    analysis, provenance = build_analysis(session, row, scenario, estimate)
    if changed:
        analysis.scope.notes = f"{analysis.scope.notes}\nEstimates were drafted before {changed} changed.".strip()
    save_new(session, analysis)
    state0 = analysis.states[0].id
    for key, d in provenance:
        session.add(FactorProvenanceRow(
            analysis_id=analysis.id, state_id=state0, factor_path=key, origin=d["choice"],
            evidence_ids=d["evidenceIds"], approved_by=d["by"], approved_at=d["at"],
            range={k: d[k] for k in ("min", "ml", "max", "conf")},
        ))
    session.add(RiskLinkRow(risk_pk=row.id, scenario_draft_id=scenario_draft.id, analysis_id=analysis.id,
                            created_at=now_iso()))
    session.commit()
    return {"analysisId": analysis.id, "factorsPushed": [k for k, _ in provenance]}


@router.get("/analyses/{analysis_id}/provenance")
def provenance(analysis_id: str, session: Session = Depends(get_session)) -> dict:
    """Where an analysis came from: its register risk, mitigation plan, and each
    pushed factor's origin and evidence. `linked` is false for other analyses."""
    link = session.scalars(select(RiskLinkRow).where(RiskLinkRow.analysis_id == analysis_id)).first()
    if link is None:
        return {"linked": False}
    risk = session.get(RiskRow, link.risk_pk)
    rows = session.scalars(select(FactorProvenanceRow).where(FactorProvenanceRow.analysis_id == analysis_id)).all()
    ids = sorted({i for r in rows for i in r.evidence_ids})
    evidence = {e.id: e for e in session.scalars(select(EvidenceItemRow).where(EvidenceItemRow.id.in_(ids)))} if ids else {}
    return {
        "linked": True,
        "riskId": risk.risk_id if risk else None,
        "riskTitle": risk.fields.get("risk_title") if risk else None,
        "mitigationPlan": risk.fields.get("mitigation_plan") if risk else None,
        "createdAt": link.created_at,
        "factors": [{
            "stateId": r.state_id, "factor": r.factor_path, "origin": r.origin, "approvedBy": r.approved_by,
            "approvedAt": r.approved_at, "range": r.range,
            "evidence": [{"id": i, "citation": evidence[i].citation, "summary": evidence[i].summary,
                          "origin": evidence[i].origin} for i in r.evidence_ids if i in evidence],
        } for r in rows],
    }
