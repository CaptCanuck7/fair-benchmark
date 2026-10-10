"""Live evaluation of the intake pipeline (AGENT_BUILD.md section 14).

Opt in: `docker compose exec api pytest -m live -s`. It runs quality, triage
and classification on the test register through the real agent service and
the Claude API, so it spends tokens. It uses a fresh in-memory database, never
your saved data.

The expectations below are for tests only. They are never part of a prompt.
Set RECORD_DIR to also save the model's outputs as JSON (used to refresh
tests/fixtures/intake_recorded.json, which the unit tests replay).
"""

import json
import os
from pathlib import Path

import pytest
from conftest import AGENT_DATA

from app import agent_client, agent_pipeline
from app.agent_client import fetch_agent_status

pytestmark = pytest.mark.live

REGISTER = AGENT_DATA / "tactical_risk_register_test.xlsx"

# risk: (quality, triage or None if not run, accepted primary condition types or None if not run/any)
EXPECTED: dict[str, tuple[str, str | None, set[str] | None]] = {
    "TR-6": ("ready", "qualifies", {"unsupported_software"}),
    "TR-7": ("ready", "qualifies", {"missing_control"}),
    "TR-8": ("ready", "qualifies", {"misconfiguration"}),
    "TR-9": ("ready", "qualifies", {"process_gap"}),
    "TR-10": ("ready", "qualifies", {"third_party", "unsupported_software"}),
    "TR-11": ("ready", "qualifies", {"missing_control"}),
    "TR-12": ("ready", "qualifies", {"process_gap"}),
    "TR-13": ("ready", "qualifies", {"missing_control", "misconfiguration", "process_gap"}),
    "TR-14": ("ready", "qualifies", {"third_party"}),
    "TR-15": ("ready", "screened_out", None),
    "TR-16": ("ready", "screened_out", None),
    "TR-17": ("needs_info", None, None),
    "TR-18": ("needs_info", None, None),
}
EXPECTED_SCORES = {"TR-6": 12, "TR-7": 15, "TR-8": 12, "TR-9": 12, "TR-10": 8, "TR-11": 8, "TR-12": 8,
                   "TR-13": 12, "TR-14": 6, "TR-15": 2, "TR-16": 4}
# Gap fields the quality result must name (section 14, "Other expectations").
EXPECTED_GAPS = {
    "TR-17": {"assets", "environment", "risk_owner", "risk_analysis"},
    "TR-18": {"baseline_likelihood", "risk_action", "assets", "risk_analysis"},
}


def test_intake_pipeline_on_the_test_register(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")

    recorded: dict[str, dict[str, dict]] = {}
    real_call = agent_client.call_task

    def recording_call(task, payload):
        res = real_call(task, payload)
        recorded.setdefault(task, {})[payload["risk"]["title"]] = res.output
        return res

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", recording_call)

    res = client.post("/api/register/import", files={"file": ("register.xlsx", REGISTER.read_bytes(),
                                                              "application/octet-stream")})
    assert res.status_code == 201, res.text
    risks = {r["riskId"]: r for r in client.get("/api/register/risks").json()}

    problems: list[str] = []
    rows = []
    tokens = [0, 0]
    for rid, (quality, triage, types) in EXPECTED.items():
        r = risks[rid]
        detail = client.get(f"/api/register/risks/{rid}").json()
        for run in detail["runs"]:
            tokens[0] += run["inputTokens"]
            tokens[1] += run["outputTokens"]
            if run["status"] != "succeeded":
                problems.append(f"{rid}: {run['task']} run {run['status']}: {run['error']}")
        rows.append(f"{rid:6} {r['quality'] or '-':11} {r['triage'] or '-':13} "
                    f"{r['classification'] or '-':21} {r['secondaryClassification'] or '':21} {r['note'] or ''}")

        if r["quality"] != quality:
            problems.append(f"{rid}: quality {r['quality']}, expected {quality}")
        if r["triage"] != triage:
            problems.append(f"{rid}: triage {r['triage']}, expected {triage}")
        t = detail["intake"]["triage"]
        if triage and t and t["effective"]["score"] != EXPECTED_SCORES[rid]:
            problems.append(f"{rid}: triage score {t['effective']['score']}")
        if types is not None and r["classification"] not in types:
            problems.append(f"{rid}: condition {r['classification']}, expected one of {sorted(types)}")
        if triage != "qualifies" and r["classification"] is not None:
            problems.append(f"{rid}: classified although it didn't qualify")
        q = detail["intake"]["quality"]
        if q and quality == "ready" and q["effective"]["status"] != "ready":
            problems.append(f"{rid}: quality blocked by {q['effective']['blockedBy']}; "
                            f"agent gaps {[g['problem'] for g in q['effective']['gaps'] if g['source'] == 'agent']}")
        if rid in EXPECTED_GAPS and q:
            gaps = {g["field"] for g in q["effective"]["gaps"]}
            if not EXPECTED_GAPS[rid] <= gaps:
                problems.append(f"{rid}: gaps {sorted(gaps)} miss {sorted(EXPECTED_GAPS[rid] - gaps)}")
            if not detail["intake"]["quality"]["effective"]["questions"]:
                problems.append(f"{rid}: no questions for the analyst")
            if detail["intake"]["triage"] is not None or detail["intake"]["classification"] is not None:
                problems.append(f"{rid}: drafted past needs_info")

    print("\nRisk   Quality     Triage        Condition             Secondary             Note")
    print("\n".join(rows))
    print(f"Tokens: {tokens[0]:,} in, {tokens[1]:,} out.")

    if os.environ.get("RECORD_DIR"):
        out = Path(os.environ["RECORD_DIR"]) / "intake_recorded.json"
        out.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded model outputs to {out}")

    assert not problems, "\n".join(problems)
