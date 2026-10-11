"""Task 7 (AGENT_BUILD.md section 9.7): input review and report drafting.

Both run on an analysis rather than a register risk, as background jobs like
the risk tasks. The review reads the saved document with the deterministic
checks beside it, and its findings never block a run. A report reads one
stored run; every number in the draft must match the run or its document
snapshot (report_check), or the draft is discarded and the run fails.
"""

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_pipeline
from app.agent_pipeline import _call, _finish, now_iso
from app.content.factors import F
from app.db import SessionLocal
from app.engine.simulate import validate_analysis
from app.models import AgentRunRow, AnalysisDraftRow, AnalysisRow, FactorProvenanceRow, RiskLinkRow, RiskRow, RunRow
from app.routers.analyses import latest_run as latest_sim_run
from app.report_check import freq, money, pct, unmatched_numbers
from app.schemas import Analysis, input_hash, new_id

log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
# Approval lines written by "Create analysis". They hold the analyst's name,
# which isn't sent to the model.
APPROVAL_LINE = re.compile(r"^(Agent-drafted, approved by|Analyst estimate by) .*$", re.MULTILINE)


class AnalysisBusy(Exception):
    pass


# --- Reading a document ------------------------------------------------------------


def get_dist(state: dict, key: str) -> dict:
    if key.startswith("primary.") or key.startswith("secondary."):
        group, form = key.split(".", 1)
        return state[group][form]
    if key == "slef":
        return state["slef"]
    return state["lef"][key]


def populated(d: dict) -> bool:
    return any(d.get(k) is not None for k in ("min", "ml", "max"))


def method_of(state: dict) -> dict:
    return {"mode": state["lef"]["mode"], "vuln_mode": state["lef"]["vulnMode"]}


def used_factors(state: dict) -> list[str]:
    from app.routers.estimates import method_factors  # local: estimates imports the register router

    return method_factors(method_of(state))


def _src(text: str) -> str:
    return APPROVAL_LINE.sub("", text or "").strip()


def factor_view(state: dict, key: str) -> dict:
    d = get_dist(state, key)
    return {"factor": key, "label": F[key]["label"], "unit": F[key]["unit"], "kind": F[key]["kind"],
            "min": d.get("min"), "ml": d.get("ml"), "max": d.get("max"), "conf": d.get("conf"),
            "rationale": _src(d.get("src", ""))}


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("min", "ml", "max", "conf"))


def changed_factors(base: dict, option: dict) -> list[dict]:
    """What a treatment changes from the current state, factor by factor."""
    out = []
    if method_of(base) != method_of(option):
        out.append({"factor": "method", "baseline": method_of(base), "option": method_of(option)})
    for key in F:
        a, b = get_dist(base, key), get_dist(option, key)
        if (populated(a) or populated(b)) and not _same(a, b):
            pick = lambda d: {k: d.get(k) for k in ("min", "ml", "max", "conf")}  # noqa: E731
            out.append({"factor": key, "baseline": pick(a), "option": pick(b)})
    return out


def linked_risk(session: Session, analysis_id: str) -> RiskRow | None:
    link = session.scalars(select(RiskLinkRow).where(RiskLinkRow.analysis_id == analysis_id)
                           .order_by(RiskLinkRow.id.desc())).first()
    return session.get(RiskRow, link.risk_pk) if link else None


# --- Payloads ------------------------------------------------------------------------


def review_payload(session: Session, row: AnalysisRow, run_id: str) -> dict[str, Any]:
    doc = row.document
    analysis = Analysis.model_validate(doc)
    states = doc["states"]
    base = states[0]

    checks = [{"level": c["level"], "message": c["message"], "state_id": c["stateId"], "path": c.get("path")}
              for c in validate_analysis(analysis) if c["level"] != "ok"]
    latest = latest_sim_run(session, row.id)
    if latest is not None and latest.input_hash == input_hash(analysis):
        for s in latest.results.get("states", []):
            checks += [{"level": c["level"], "message": c["message"], "state_id": s["stateId"], "path": c.get("path")}
                       for c in s.get("checks", []) if c["level"] != "ok"]
        for c in (latest.results.get("comparison") or {}).get("checks", []):
            if c["level"] != "ok":
                checks.append({"level": c["level"], "message": c["message"], "state_id": None, "path": c.get("path")})

    evidence, provenance = [], []
    risk = linked_risk(session, row.id)
    if risk is not None:
        items, _ = agent_pipeline.current_evidence(session, risk.id)
        evidence = [{"id": e.id, "origin": e.origin, "citation": e.citation, "summary": e.summary,
                     "value": e.value, "unit": e.unit, "factors": e.factors or [], "stale": e.stale} for e in items]
        provenance = [{"state_id": p.state_id, "factor": p.factor_path, "origin": p.origin,
                       "evidence_ids": p.evidence_ids or []}
                      for p in session.scalars(select(FactorProvenanceRow)
                                               .where(FactorProvenanceRow.analysis_id == row.id))]
    return {
        "agent_run_id": run_id,
        "analysis": {"title": doc.get("title", ""), "scope": doc.get("scope", {})},
        "states": [{
            "id": s["id"], "name": s["name"], "baseline": i == 0, "notes": s.get("notes", ""), "cost": s.get("cost"),
            "method": method_of(s),
            "factors": [factor_view(s, k) for k in used_factors(s)],
            "changes": changed_factors(base, s) if i else [],
        } for i, s in enumerate(states)],
        "checks": checks,
        "evidence": evidence,
        "provenance": provenance,
    }


def residual_choice(results: dict) -> str | None:
    """The treatment the exception justification compares with the current
    state: the best net benefit where costs are entered, else the largest
    reduction. None without treatments."""
    rows = ((results.get("comparison") or {}).get("rows") or [])[1:]
    if not rows:
        return None
    costed = [r for r in rows if r.get("netBenefit") is not None]
    best = max(costed, key=lambda r: r["netBenefit"]) if costed else max(rows, key=lambda r: r.get("reduction") or 0)
    return best["stateId"]


def option_figures(s: dict, threshold: float | None) -> dict[str, str]:
    figs = {
        "Average annual loss": money(s["meanAnnualLoss"]),
        "Annual loss in a typical year (median)": money(s["p50"]),
        "Annual loss in a bad year (90th percentile)": money(s["p90"]),
        "Annual loss in a severe year (95th percentile)": money(s["p95"]),
        "Chance of any loss in a year": pct(s["chanceAnyLoss"]),
        "Loss events expected per year": freq(s["lefMean"]),
        "Typical cost of one loss event (median)": money(s["singleLossP50"]),
        "Share of loss from secondary effects (regulators, customers, reputation)": pct(s["secondaryShareOfLoss"]),
    }
    if threshold is not None and s.get("chanceAboveThreshold") is not None:
        figs["Chance of annual loss above the threshold"] = pct(s["chanceAboveThreshold"])
    if s.get("cost") is not None:
        figs["Annual cost of this option"] = money(s["cost"])
    return {k: v for k, v in figs.items() if v is not None}


def comparison_figures(r: dict) -> dict[str, str]:
    red = r.get("reduction") or 0.0
    figs = {
        "Change in average annual loss": f"{money(red)} {'lower' if red >= 0 else 'higher'} than the current state",
        "Change as a share of current loss": f"{pct(r['reductionPct'])} {'lower' if red >= 0 else 'higher'}",
    }
    if r.get("cost") is not None:
        figs["Annual cost"] = money(r["cost"])
    nb = r.get("netBenefit")
    if nb is not None:
        figs["Net benefit"] = (f"saves {money(nb)} a year more than it costs" if nb >= 0
                               else f"costs {money(nb)} a year more than it saves")
    if r.get("return") is not None:
        figs["Loss reduced per dollar spent"] = f"${freq(r['return'])}"
    return figs


def report_payload(session: Session, run: RunRow, agent_run_id: str) -> dict[str, Any]:
    doc, res = run.document_snapshot, run.results
    threshold = res.get("threshold")
    residual = residual_choice(res)
    rows = {r["stateId"]: r for r in ((res.get("comparison") or {}).get("rows") or [])}
    notes = {s["id"]: s.get("notes", "") for s in doc["states"]}
    options = []
    for i, s in enumerate(res["states"]):
        options.append({
            "state_id": s["stateId"], "name": s["name"], "baseline": i == 0, "notes": notes.get(s["stateId"], ""),
            "figures": option_figures(s, threshold),
            "compared_with_current": comparison_figures(rows[s["stateId"]]) if i and s["stateId"] in rows else None,
            "checks": [c["message"] for c in s.get("checks", []) if c["level"] in ("warn", "info")],
        })
    risk = linked_risk(session, run.analysis_id)
    return {
        "agent_run_id": agent_run_id,
        "analysis": {"title": doc.get("title", ""), "scope": doc.get("scope", {})},
        "risk": ({"title": risk.fields.get("risk_title"), "mitigation_plan": risk.fields.get("mitigation_plan"),
                  "risk_action": risk.fields.get("risk_action")} if risk else None),
        "run": {"simulated_years": f"{res['iterations']:,}",
                "loss_threshold": money(threshold) if threshold is not None else None},
        "options": options,
        "residual_state_id": residual,
    }


# --- Jobs ----------------------------------------------------------------------------


def is_busy(session: Session, analysis_id: str) -> bool:
    return session.scalars(select(AgentRunRow.id).where(AgentRunRow.analysis_id == analysis_id,
                                                        AgentRunRow.status.in_(ACTIVE))).first() is not None


def _new_run(session: Session, analysis_id: str, task: str) -> AgentRunRow:
    run = AgentRunRow(id=new_id(), analysis_id=analysis_id, task=task, status="queued", started_at=now_iso())
    session.add(run)
    session.commit()
    return run


def queue(session: Session, analysis_id: str, task: str, run_id: str | None = None) -> str:
    if is_busy(session, analysis_id):
        raise AnalysisBusy("The agent is already working on this analysis.")
    run = _new_run(session, analysis_id, task)
    agent_pipeline.submit(_job, None, run.id, run_id)
    return run.id


def _job(_risk_pk: None, agent_run_id: str, run_id: str | None) -> None:
    try:
        with SessionLocal() as s:
            run = s.get(AgentRunRow, agent_run_id)
            if run.task == "review":
                _review(s, run)
            else:
                _report(s, run, s.get(RunRow, run_id))
    except Exception:  # never leave the run "running"
        log.exception("analysis agent job failed")
        with SessionLocal() as s:
            run = s.get(AgentRunRow, agent_run_id)
            if run is not None and run.status in ACTIVE:
                _finish(run, "failed", error="The job stopped unexpectedly. Try again.")
                s.commit()


def _review(s: Session, run: AgentRunRow) -> None:
    row = s.get(AnalysisRow, run.analysis_id)
    payload = review_payload(s, row, run.id)
    res = _call(s, run, "review", payload)
    if res is None:
        return
    s.add(AnalysisDraftRow(analysis_id=row.id, kind="review", payload=res.output, agent_run_id=run.id,
                           input_hash=input_hash(Analysis.model_validate(row.document)), created_at=now_iso()))
    s.commit()


def report_names(run: RunRow) -> list[str]:
    doc = run.document_snapshot
    return [doc.get("title", ""), *(s.get("name", "") for s in doc.get("states", []))]


def _report(s: Session, run: AgentRunRow, sim: RunRow) -> None:
    payload = report_payload(s, sim, run.id)
    res = _call(s, run, "report", payload)
    if res is None:
        return
    out = res.output
    bad = unmatched_numbers([out.get("leadership_summary"), out.get("exception_justification")],
                            sim.results, sim.document_snapshot, report_names(sim))
    if bad:
        # Section 9.7: a number that isn't in the run means the draft is discarded.
        _finish(run, "failed", error="The draft was discarded: these numbers aren’t in the run results or the "
                                     f"analysis: {', '.join(dict.fromkeys(bad))}. Draft it again.")
        s.commit()
        return
    residual = payload["residual_state_id"]
    names = {o["state_id"]: o["name"] for o in payload["options"]}
    s.add(AnalysisDraftRow(
        analysis_id=sim.analysis_id, run_id=sim.id, kind="report", agent_run_id=run.id, input_hash=sim.input_hash,
        created_at=now_iso(),
        payload={"leadershipSummary": out["leadership_summary"],
                 "exceptionJustification": out.get("exception_justification"),
                 "residualStateId": residual, "residualName": names.get(residual) if residual else None},
    ))
    s.commit()
