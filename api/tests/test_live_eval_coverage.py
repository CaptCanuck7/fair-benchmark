"""Live check of required lookups (AGENT_FIXES.md fix 7).

Opt in: `docker compose exec api pytest -m live -s tests/test_live_eval_coverage.py`.
Intake and scenarios are replayed; evidence gathering calls the real agent,
the Claude API, the public feeds and web search for the two third-party risks.
The agent writes its outbound log to the running api, which is read back here.

The library lookup goes to the api, not outbound, so it is confirmed from the
run's coverage rather than the outbound log.
"""

import json
import os

import httpx
import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult, fetch_agent_status

pytestmark = pytest.mark.live

RECORDED = {**json.loads((FIXTURES / "intake_recorded.json").read_text(encoding="utf-8")),
            **json.loads((FIXTURES / "scenario_recorded.json").read_text(encoding="utf-8"))}
# The running api, where the agent logs. From a one-off container, pass LIVE_API=http://api:8000.
LIVE_API = os.environ.get("LIVE_API", "http://localhost:8000")
THIRD_PARTY = ["TR-10", "TR-14"]


def test_required_lookups_on_third_party_risks(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")
    if not status.get("externalEnabled", True):
        pytest.skip("External sources are off on the Settings page.")
    real_call = agent_client.call_task

    def call(task, payload):
        if task in ("quality", "triage", "classify", "scenario"):
            return TaskResult(output=RECORDED[task][payload["risk"]["title"]], model="recorded",
                              prompt_version=f"{task}.v1", input_tokens=0, output_tokens=0)
        return real_call(task, payload)

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})

    problems = []
    for rid in THIRD_PARTY:
        client.post(f"/api/agent/risks/{rid}/scenario")
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        client.post(f"/api/agent/risks/{rid}/evidence")
        d = client.get(f"/api/register/risks/{rid}").json()
        run = next(r for r in d["runs"] if r["task"] == "evidence")
        if run["status"] != "succeeded":
            problems.append(f"{rid}: evidence run {run['status']}: {run['error']}")
            continue
        cov = d["evidenceRun"]["coverage"]
        tools = cov["tools"]
        print(f"\n{rid}: {d['evidenceRun']['toolCalls']} calls, budget spent: {cov['budgetSpent']}")
        for name, t in tools.items():
            print(f"  {name:18} offered={t['offered']!s:5} required={t['required']!s:5} calls={t['calls']} "
                  f"blocked={t['blocked']} failed={t['failed']} items={t['items']} reason={t['reason']}")
        for name in ("library_lookup", "nvd_search", "web_search"):
            if not tools[name]["required"]:
                problems.append(f"{rid}: {name} wasn't required")
            if tools[name]["calls"] == 0:
                problems.append(f"{rid}: {name} wasn't attempted")
        log = httpx.get(f"{LIVE_API}/api/agent/outbound-log", params={"limit": 1000}, timeout=10).json()
        used = {e["tool"] for e in log if e["agentRunId"] == run["id"]}
        print(f"  outbound log tools for this run: {sorted(used)}")
        for tool in ("nvd", "web_search"):
            if tool not in used:
                problems.append(f"{rid}: no {tool} entry in the outbound log")
    assert not problems, "\n".join(problems)
