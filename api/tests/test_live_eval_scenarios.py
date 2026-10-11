"""Live evaluation of scenario scoping and attack vectors (AGENT_BUILD.md section 14).

Opt in: `docker compose exec api pytest -m live -s tests/test_live_eval_scenarios.py`.
The intake checks are replayed from fixtures/intake_recorded.json; the
scenario and vectors tasks call the real agent and the Claude API for the 9
qualifying risks (18 calls). Each scenario is approved, as an analyst would,
before its vectors are drafted. Uses a throwaway in-memory database.

Set RECORD_DIR to save the outputs as scenario_recorded.json, which
test_scenario_replay.py replays.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult, fetch_agent_status

pytestmark = pytest.mark.live

INTAKE = json.loads((FIXTURES / "intake_recorded.json").read_text(encoding="utf-8"))
QUALIFYING = ["TR-6", "TR-7", "TR-8", "TR-9", "TR-10", "TR-11", "TR-12", "TR-13", "TR-14"]
WITH_EXPLOIT_PATHS = {"TR-6", "TR-7", "TR-8", "TR-10", "TR-13"}


def test_scenarios_and_vectors_on_qualifying_risks(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")

    recorded: dict[str, dict] = {"scenario": {}, "vectors": {}}
    real_call = agent_client.call_task

    def call(task, payload):
        title = payload["risk"]["title"]
        if task in INTAKE:
            return TaskResult(output=INTAKE[task][title], model="recorded", prompt_version=f"{task}.v1",
                              input_tokens=0, output_tokens=0)
        res = real_call(task, payload)
        recorded[task][title] = res.output
        return res

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    assert client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(),
                                                               "application/octet-stream")}).status_code == 201

    problems: list[str] = []
    rows: list[str] = []
    tokens = [0, 0]
    for rid in QUALIFYING:
        res = client.post(f"/api/agent/risks/{rid}/scenario")
        if res.status_code != 202:
            problems.append(f"{rid}: scenario didn't start: {res.json().get('detail')}")
            continue
        d = client.get(f"/api/register/risks/{rid}").json()
        if d["scenario"] is None:
            problems.append(f"{rid}: scenario run failed: {d['runs'][0]['error']}")
            continue
        s = d["scenario"]["effective"]
        client.put(f"/api/drafts/{d['scenario']['id']}", json={"action": "approve"})
        client.post(f"/api/agent/risks/{rid}/vectors")
        d = client.get(f"/api/register/risks/{rid}").json()
        for run in d["runs"]:
            if run["task"] in ("scenario", "vectors"):
                tokens[0] += run["inputTokens"]
                tokens[1] += run["outputTokens"]
        if d["vectors"] is None:
            problems.append(f"{rid}: vectors run failed: {d['runs'][0]['error']}")
            continue
        v = d["vectors"]["effective"]
        origins = {p["origin"] for p in v["paths"]}
        rows.append(f"{rid:6} {s['threat_type']:27} {s['effect']:16} {len(s['controls']):2} controls "
                    f"{len(s['alternatives'])} alt  {v['kind']:15} {len(v['paths'])} paths {'/'.join(sorted(origins))}")

        # Every scenario: controls tagged, unhelpful controls explained.
        for c in s["controls"]:
            if not c["helps"] and not (c.get("note") or "").strip():
                problems.append(f"{rid}: control '{c['control']}' marked unhelpful without a note")
        # Malicious threat types get attack vectors; others get failure paths.
        want = "failure_paths" if s["threat_type"] in ("Error (accidental)", "Failure (system or vendor)",
                                                         "Natural") else "attack_vectors"
        if v["kind"] != want:
            problems.append(f"{rid}: {v['kind']} for threat type {s['threat_type']}")
        want_origin = "from_register" if rid in WITH_EXPLOIT_PATHS else "agent_drafted"
        if origins != {want_origin}:
            problems.append(f"{rid}: path origins {origins}, expected {want_origin}")

        if rid == "TR-6" and (s["threat_type"], s["effect"]) != ("Malicious, external", "Confidentiality"):
            problems.append(f"TR-6: {s['threat_type']} / {s['effect']}, expected Malicious, external / Confidentiality")
        if rid == "TR-12":
            if not s["threat_type"].startswith("Failure") or s["effect"] != "Availability":
                problems.append(f"TR-12: {s['threat_type']} / {s['effect']}, expected Failure / Availability")
            if v["kind"] != "failure_paths":
                problems.append("TR-12: expected failure paths")
        if rid == "TR-10" and not any(a["effect"] == "Availability" for a in s["alternatives"]):
            problems.append(f"TR-10: no availability alternative (provider retirement); got "
                            f"{[(a['title'], a['effect']) for a in s['alternatives']]}")

    for rid in ("TR-15", "TR-16", "TR-17", "TR-18"):
        if client.post(f"/api/agent/risks/{rid}/scenario").status_code != 409:
            problems.append(f"{rid}: a scenario was allowed")

    print("\nRisk   Threat type                 Effect           Scenario detail        Vectors")
    print("\n".join(rows))
    print(f"Tokens (scenario + vectors): {tokens[0]:,} in, {tokens[1]:,} out.")
    if os.environ.get("RECORD_DIR"):
        out = Path(os.environ["RECORD_DIR"]) / "scenario_recorded.json"
        out.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded model outputs to {out}")
    assert not problems, "\n".join(problems)
