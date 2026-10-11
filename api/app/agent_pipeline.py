"""The intake pipeline (AGENT_BUILD.md section 6, steps 1 to 3), run as jobs.

For each risk: quality check, then triage, then condition classification.
Each step stops the pipeline when its condition fails:

- needs_info stops after the quality check: no triage, no classification.
- screened_out stops after triage, unless the analyst overrides it.

Every step is an `agent_runs` row (queued, running, succeeded or failed) and
stores its result as a draft. Jobs run in a small thread pool so the import
request returns at once; the UI polls. Plain Python decides the order and the
rules; the agent service only does the model's part of each step.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_client
from app.agent_client import AgentCallError
from app.config import settings
from app.db import SessionLocal
from app.models import (
    AgentRunRow,
    DataRequestRow,
    DraftRow,
    EvidenceItemRow,
    EvidenceRunRow,
    ReferenceLibraryRow,
    RiskRow,
)
from app.register.drafts import usable
from app.register.parser import score_input
from app.register.quality import combine, rule_gaps
from app.register.state import ACTIVE, INTAKE, intake_states, task_blocker
from app.register.triage import triage, would_qualify
from app.schemas import new_id


def now_iso() -> str:
    """UTC timestamp with microseconds, so runs started in quick succession
    still sort in the order they started."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

log = logging.getLogger(__name__)

TASKS = INTAKE
INTERRUPTED = "Stopped when the api restarted. Run the checks again."

_executor = ThreadPoolExecutor(max_workers=settings.agent_workers, thread_name_prefix="agent-job")


def submit(fn: Callable[..., None], risk_pk: int, *args: Any) -> None:
    """Run a job for one risk in the background. Tests replace this to run jobs inline."""
    _executor.submit(_guarded, fn, risk_pk, *args)


def _guarded(fn: Callable[..., None], risk_pk: int, *args: Any) -> None:
    try:
        fn(risk_pk, *args)
    except Exception:  # a job must never die silently with its runs left "running"
        log.exception("agent job failed")
        with SessionLocal() as s:
            for run in s.scalars(select(AgentRunRow).where(AgentRunRow.risk_pk == risk_pk,
                                                           AgentRunRow.status.in_(ACTIVE))):
                _finish(run, "failed", error="The job stopped unexpectedly. Run the checks again.")
            s.commit()


# --- Inputs --------------------------------------------------------------------


def risk_entry(row: RiskRow) -> dict[str, Any]:
    """What the agent sees of a risk (schemas.RiskEntry). No people's names."""
    f = row.fields
    return {
        "title": f.get("risk_title"),
        "category": f.get("risk_category"),
        "asset_ids": f.get("asset_ids", []),
        "environment": f.get("environment"),
        "risk_action": f.get("risk_action"),
        "baseline_impact": score_input(f.get("baseline_impact")),
        "baseline_likelihood": score_input(f.get("baseline_likelihood")),
        "baseline_score": row.baseline_score,
        "mitigation_plan": f.get("mitigation_plan"),
        "structured": row.structured,
        "sections": row.sections,
    }


def input_hash(task: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps({"task": task, "payload": payload}, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def quality_payload(row: RiskRow) -> dict[str, Any]:
    gaps = rule_gaps(row.fields, row.sections, row.structured)
    return {"risk": risk_entry(row), "rule_gaps": [{"field": g.field, "problem": g.problem} for g in gaps]}


def quality_hash(row: RiskRow) -> str:
    # The threshold is part of the hash: it decides which gaps block.
    return input_hash("quality", {**quality_payload(row), "threshold": settings.triage_min_score})


# --- Lookups -------------------------------------------------------------------


def latest_draft(session: Session, risk_pk: int, kind: str) -> DraftRow | None:
    return session.scalars(select(DraftRow).where(DraftRow.risk_pk == risk_pk, DraftRow.kind == kind)
                           .order_by(DraftRow.id.desc()).limit(1)).first()


def latest_run(session: Session, risk_pk: int, task: str) -> AgentRunRow | None:
    return session.scalars(select(AgentRunRow).where(AgentRunRow.risk_pk == risk_pk, AgentRunRow.task == task)
                           .order_by(AgentRunRow.started_at.desc(), AgentRunRow.id.desc()).limit(1)).first()


def is_busy(session: Session, risk_pk: int) -> bool:
    return session.scalars(select(AgentRunRow.id).where(AgentRunRow.risk_pk == risk_pk,
                                                        AgentRunRow.status.in_(ACTIVE)).limit(1)).first() is not None


# --- Runs ----------------------------------------------------------------------


def _new_run(session: Session, risk_pk: int, task: str, status: str = "queued") -> AgentRunRow:
    run = AgentRunRow(id=new_id(), risk_pk=risk_pk, task=task, status=status, started_at=now_iso(),
                      input_tokens=0, output_tokens=0)
    session.add(run)
    return run


def _finish(run: AgentRunRow, status: str, error: str | None = None) -> None:
    run.status, run.error, run.finished_at = status, error, now_iso()


def _call(session: Session, run: AgentRunRow, task: str, payload: dict[str, Any],
          hash_value: str | None = None) -> agent_client.TaskResult | None:
    """Run one agent task for `run`, recording the outcome. None if it failed."""
    run.status, run.started_at = "running", now_iso()
    run.input_hash = hash_value or input_hash(task, payload)
    session.commit()
    try:
        res = agent_client.call_task(task, payload)
    except AgentCallError as exc:
        u = exc.usage
        run.model = u.get("model") or run.model
        run.prompt_version = u.get("prompt_version") or run.prompt_version
        run.input_tokens, run.output_tokens = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        _finish(run, "failed", error=exc.message)
        session.commit()
        return None
    run.model, run.prompt_version = res.model, res.prompt_version
    run.input_tokens, run.output_tokens = res.input_tokens, res.output_tokens
    _finish(run, "succeeded")
    session.commit()
    return res


def _draft(session: Session, risk_pk: int, kind: str, payload: dict[str, Any], run: AgentRunRow | None) -> DraftRow:
    d = DraftRow(risk_pk=risk_pk, kind=kind, payload=payload, status="drafted",
                 agent_run_id=run.id if run else None)
    session.add(d)
    session.commit()
    return d


# --- Queueing ------------------------------------------------------------------


def queue_intake(session: Session, rows: list[RiskRow], force: bool = False) -> list[str]:
    """Queue the intake pipeline for each risk. Unless `force`, a risk whose
    quality check already succeeded on the same input is skipped. Returns the
    risk IDs queued."""
    queued: list[str] = []
    jobs: list[tuple[int, str]] = []
    for row in rows:
        if is_busy(session, row.id):
            continue
        if not force:
            prev = latest_run(session, row.id, "quality")
            if prev and prev.status == "succeeded" and prev.input_hash == quality_hash(row) \
                    and latest_draft(session, row.id, "quality"):
                continue
        run = _new_run(session, row.id, "quality")
        jobs.append((row.id, run.id))
        queued.append(row.risk_id)
    session.commit()
    for risk_pk, run_id in jobs:
        submit(run_intake, risk_pk, run_id)
    return queued


def queue_classification(session: Session, row: RiskRow) -> str:
    run = _new_run(session, row.id, "classification")
    session.commit()
    submit(run_classification, row.id, run.id)
    return run.id


# --- Jobs ----------------------------------------------------------------------


def run_intake(risk_pk: int, quality_run_id: str) -> None:
    with SessionLocal() as s:
        row = s.get(RiskRow, risk_pk)
        run = s.get(AgentRunRow, quality_run_id)
        if row is None or run is None:
            return

        # 1. Quality check: rules, then the model's judgement of the text.
        payload = quality_payload(row)
        res = _call(s, run, "quality", payload, hash_value=quality_hash(row))
        if res is None:
            return
        qualifies = would_qualify(row.baseline_score, row.fields.get("baseline_impact"), settings.triage_min_score)
        quality = combine(rule_gaps(row.fields, row.sections, row.structured), qualifies, res.output)
        _draft(s, risk_pk, "quality", quality, run)
        if quality["status"] != "ready":
            return

        # 2. Triage: the rule decides; the model explains and may add an advisory.
        _run_triage(s, row)


def _run_triage(s: Session, row: RiskRow) -> None:
    rule = triage(row.baseline_score, row.fields.get("baseline_impact"), settings.triage_min_score)
    run = _new_run(s, row.id, "triage", status="running")
    res = _call(s, run, "triage", {"risk": risk_entry(row), "rule": rule})
    note = res.output if res else {}
    _draft(s, row.id, "triage", {
        **rule,
        "reason": note.get("reason"),
        "advisory": note.get("advisory"),
        # The rule stands even when the model's explanation failed.
        "noteError": None if res else run.error,
    }, run)
    if rule["status"] != "qualifies":
        return

    # 3. Condition classification.
    _classify(s, row, _new_run(s, row.id, "classification", status="running"))


def run_classification(risk_pk: int, run_id: str) -> None:
    with SessionLocal() as s:
        row, run = s.get(RiskRow, risk_pk), s.get(AgentRunRow, run_id)
        if row is not None and run is not None:
            _classify(s, row, run)


def _classify(s: Session, row: RiskRow, run: AgentRunRow) -> None:
    res = _call(s, run, "classify", {"risk": risk_entry(row)})
    if res is not None:
        _draft(s, row.id, "classification", res.output, run)


def fail_interrupted(session: Session) -> int:
    """At startup: runs left queued or running by a stopped api can't finish."""
    runs = session.scalars(select(AgentRunRow).where(AgentRunRow.status.in_(ACTIVE))).all()
    for run in runs:
        _finish(run, "failed", error=INTERRUPTED)
    session.commit()
    return len(runs)


# --- Scenario and vectors (pipeline step 4, started by the analyst) -------------

RISK_TASKS = ("scenario", "vectors", "evidence", "estimates")


class TaskBlocked(Exception):
    """A risk task that can't start yet. The message says why, for the analyst."""


def scenario_hash(scenario: dict[str, Any]) -> str:
    return input_hash("scenario-content", scenario)


def queue_risk_task(session: Session, row: RiskRow, task: str) -> str:
    """Queue `scenario` or `vectors` for one risk, after checking it may run."""
    state = intake_states(session, [row.id])[row.id]
    if state.busy:
        raise TaskBlocked("The agent is already working on this risk. Try again when it finishes.")
    reason = task_blocker(state, task, has_evidence=latest_evidence_run(session, row.id) is not None)
    if reason:
        raise TaskBlocked(reason)
    run = _new_run(session, row.id, task)
    session.commit()
    submit(run_risk_task, row.id, run.id)
    return run.id


def run_risk_task(risk_pk: int, run_id: str) -> None:
    with SessionLocal() as s:
        row, run = s.get(RiskRow, risk_pk), s.get(AgentRunRow, run_id)
        if row is None or run is None:
            return
        state = intake_states(s, [risk_pk])[risk_pk]
        # Re-check: the drafts may have changed while the job was queued.
        reason = task_blocker(state, run.task, has_evidence=latest_evidence_run(s, risk_pk) is not None)
        if reason:
            _finish(run, "failed", error=reason)
            s.commit()
            return
        if run.task == "scenario":
            classification = state.get("classification")
            payload = {"risk": risk_entry(row), "classification": (
                {"primary_type": classification["primary_type"],
                 "secondary_type": classification.get("secondary_type")} if classification else None)}
            res = _call(s, run, "scenario", payload)
            if res is not None:
                _draft(s, risk_pk, "scenario", res.output, run)
        elif run.task == "evidence":
            _gather_evidence(s, row, run, state)
        elif run.task == "estimates":
            _draft_estimates(s, row, run, state)
        else:
            scenario_draft = state.drafts["scenario"]
            scenario = {k: v for k, v in usable(scenario_draft).items() if k != "basedOn"}
            res = _call(s, run, "vectors", {"risk": risk_entry(row), "scenario": scenario})
            if res is not None:
                _draft(s, risk_pk, "vectors", {
                    **res.output,
                    # Which approved scenario these were built from, to flag them if it changes.
                    "basedOn": {"scenarioDraftId": scenario_draft.id, "scenarioHash": scenario_hash(scenario)},
                }, run)


# --- Evidence gathering (pipeline step 5) ---------------------------------------


def evidence_payload(row: RiskRow, run_id: str, state) -> dict[str, Any]:
    scenario = {k: v for k, v in usable(state.drafts["scenario"]).items() if k != "basedOn"}
    vectors = usable(state.drafts.get("vectors"))
    classification = state.get("classification")
    return {
        "agent_run_id": run_id,
        "risk": risk_entry(row),
        "scenario": scenario,
        "vectors": {k: v for k, v in vectors.items() if k != "basedOn"} if vectors else None,
        "classification": ({"primary_type": classification["primary_type"],
                            "secondary_type": classification.get("secondary_type")} if classification else None),
    }


def _gather_evidence(s: Session, row: RiskRow, run: AgentRunRow, state) -> None:
    res = _call(s, run, "evidence", evidence_payload(row, run.id, state))
    if res is None:
        return
    out = res.output
    for item in out["items"]:
        s.add(EvidenceItemRow(
            risk_pk=row.id, agent_run_id=run.id, origin=item["origin"], source_type=item["source_type"],
            source_name=item["source_name"], citation=item["citation"], published_at=item.get("published_at"),
            retrieved_at=item["retrieved_at"], summary=item["summary"], value=item.get("value"),
            unit=item.get("unit"), factors=item["factors"], stale=bool(item.get("stale")),
        ))
    for req in out["data_requests"]:
        s.add(DataRequestRow(risk_pk=row.id, agent_run_id=run.id, team=req["team"], question=req["question"],
                             factor=req["factor"], reason=req["reason"], status="open"))
    s.add(EvidenceRunRow(agent_run_id=run.id, risk_pk=row.id, tool_calls=int(out.get("tool_calls") or 0),
                         rejected=out.get("rejected") or [], notes=out.get("notes") or {}))
    s.commit()


# --- Reference library refresh ---------------------------------------------------


def queue_library_refresh(session: Session) -> str:
    busy = session.scalars(select(AgentRunRow.id).where(AgentRunRow.task == "library",
                                                        AgentRunRow.status.in_(ACTIVE)).limit(1)).first()
    if busy:
        raise TaskBlocked("A library refresh is already running.")
    run = AgentRunRow(id=new_id(), risk_pk=None, task="library", status="queued", started_at=now_iso(),
                      input_tokens=0, output_tokens=0)
    session.add(run)
    session.commit()
    # No risk: the job guard fails this run (risk_pk IS NULL) if the job crashes.
    submit(_library_job, None, run.id)
    return run.id


def _library_job(_risk_pk: None, run_id: str) -> None:
    run_library_refresh(run_id)


def run_library_refresh(run_id: str) -> None:
    with SessionLocal() as s:
        run = s.get(AgentRunRow, run_id)
        if run is None:
            return
        existing = [{"metric": r.metric, "edition": r.edition, "url": r.url}
                    for r in s.scalars(select(ReferenceLibraryRow))]
        res = _call(s, run, "library", {"agent_run_id": run_id, "existing": existing})
        if res is None:
            return
        seen = {(e["metric"].lower(), e["edition"].lower(), e["url"]) for e in existing}
        for e in res.output["entries"]:
            key = (e["metric"].lower(), e["edition"].lower(), e["url"])
            if key in seen:
                continue
            seen.add(key)
            s.add(ReferenceLibraryRow(
                metric=e["metric"], value=e["value"], unit=e["unit"], segment=e.get("segment"), source=e["source"],
                edition=e["edition"], url=e["url"], page=e.get("page"), retrieved_at=e["retrieved_at"],
                quote=e.get("quote"), status="proposed", agent_run_id=run_id,
            ))
        s.commit()


# --- First-pass estimates (pipeline step 6) -------------------------------------


def latest_evidence_run(session: Session, risk_pk: int) -> AgentRunRow | None:
    return session.scalars(select(AgentRunRow).where(AgentRunRow.risk_pk == risk_pk, AgentRunRow.task == "evidence",
                                                     AgentRunRow.status == "succeeded")
                           .order_by(AgentRunRow.started_at.desc()).limit(1)).first()


def current_evidence(session: Session, risk_pk: int) -> tuple[list[EvidenceItemRow], list[DataRequestRow]]:
    """The evidence and data requests a risk shows: the latest evidence run's,
    plus every answered request and the evidence its answer created."""
    latest = latest_evidence_run(session, risk_pk)
    run_id = latest.id if latest else None
    # Requests raised by the estimates run that followed, for factors left unestimated.
    est = session.scalars(select(AgentRunRow.id).where(AgentRunRow.risk_pk == risk_pk, AgentRunRow.task == "estimates",
                                                       AgentRunRow.status == "succeeded")
                          .order_by(AgentRunRow.started_at.desc()).limit(1)).first()
    requests = session.scalars(select(DataRequestRow).where(DataRequestRow.risk_pk == risk_pk)
                               .order_by(DataRequestRow.id)).all()
    shown = [r for r in requests if r.agent_run_id in (run_id, est) or r.status == "answered"]
    ids = {r.id for r in shown}
    items = session.scalars(select(EvidenceItemRow).where(EvidenceItemRow.risk_pk == risk_pk)
                            .order_by(EvidenceItemRow.id)).all()
    return [e for e in items if (run_id and e.agent_run_id == run_id) or e.data_request_id in ids], shown


def estimates_payload(session: Session, row: RiskRow, run_id: str, state) -> dict[str, Any]:
    items, requests = current_evidence(session, row.id)
    scenario = {k: v for k, v in usable(state.drafts["scenario"]).items() if k != "basedOn"}
    vectors = usable(state.drafts.get("vectors"))
    return {
        "agent_run_id": run_id,
        "risk": risk_entry(row),
        "scenario": scenario,
        "vectors": {k: v for k, v in vectors.items() if k != "basedOn"} if vectors else None,
        "evidence": [{"id": e.id, "origin": e.origin, "source_type": e.source_type, "source_name": e.source_name,
                      "citation": e.citation, "summary": e.summary, "value": e.value, "unit": e.unit,
                      "factors": e.factors, "stale": e.stale} for e in items],
        "data_requests": [{"id": r.id, "team": r.team, "question": r.question, "factor": r.factor,
                           "status": r.status, "answer": r.answer} for r in requests],
    }


def _draft_estimates(s: Session, row: RiskRow, run: AgentRunRow, state) -> None:
    res = _call(s, run, "estimates", estimates_payload(s, row, run.id, state))
    if res is None:
        return
    out = res.output
    # A new data request for an unestimated factor is stored like any other,
    # and the estimate points to it.
    for u in out["unestimated"]:
        new = u.pop("new_request", None)
        if u.get("data_request_id") is None and new:
            req = DataRequestRow(risk_pk=row.id, agent_run_id=run.id, team=new["team"], question=new["question"],
                                 factor=u["factor"], reason=new["reason"], status="open")
            s.add(req)
            s.flush()
            u["data_request_id"] = req.id
    _draft(s, row.id, "estimate", out, run)
