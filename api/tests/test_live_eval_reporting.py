"""Live evaluation of input review and report drafting (AGENT_BUILD.md section 9.7).

Opt in: `docker compose exec api pytest -m live -s tests/test_live_eval_reporting.py`.
TR-6 is replayed from the recorded fixtures up to its estimates, then an
analysis is created from them with a treatment option that has two planted
problems: a change its notes don't explain, and a vulnerability entered as a
fraction (0.03 for 3%). Review and report call the real agent and the Claude
API (two calls). Everything uses a throwaway in-memory database.

Set RECORD_DIR to save the outputs as reporting_recorded.json.
"""

import copy
import json
import os
from pathlib import Path

import pytest
from conftest import FIXTURES

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult, fetch_agent_status

pytestmark = pytest.mark.live

RECORDED = {}
for name in ("intake_recorded.json", "scenario_recorded.json", "evidence_recorded.json", "estimates_recorded.json"):
    RECORDED.update(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
REPLAYED = ("quality", "triage", "classify", "scenario", "evidence", "estimates")
TREATMENT_NOTES = "Migrate both servers to the supported platform. Patching then cuts the attack success rate to about 3%."


def tr6_analysis(client) -> str:
    """Import, replay TR-6 to its estimates, take every agent range, and create
    the analysis with a planted-problem treatment. Returns the analysis ID."""
    from test_live_eval import REGISTER

    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})
    client.post("/api/agent/risks/TR-6/scenario")
    sid = client.get("/api/register/risks/TR-6").json()["scenario"]["id"]
    client.put(f"/api/drafts/{sid}", json={"action": "approve"})
    assert client.post("/api/agent/risks/TR-6/evidence").status_code == 202
    assert client.post("/api/agent/risks/TR-6/estimates").status_code == 202
    est = client.get("/api/register/risks/TR-6").json()["estimates"]
    for f in est["factors"]:
        if f["status"] == "estimated":
            client.post(f"/api/register/risks/TR-6/estimates/{f['factor']}/reveal", json={"analystRange": None})
            assert client.put(f"/api/register/risks/TR-6/estimates/{f['factor']}",
                              json={"choice": "agent"}).status_code == 200
    aid = client.post("/api/register/risks/TR-6/create-analysis").json()["analysisId"]

    doc = client.get(f"/api/analyses/{aid}").json()
    base = doc["states"][0]
    if not any(base["primary"][k]["ml"] is not None for k in base["primary"]):
        base["primary"]["response"].update(min=3000, ml=6750, max=20000, conf="med", src="Incident hours.")
    base["lef"]["vulnMode"] = "direct"
    if base["lef"]["vuln"]["ml"] is None:
        base["lef"]["vuln"].update(min=2, ml=8, max=20, conf="med", src="Open critical finding.")
    t = copy.deepcopy(base)
    t.update(id="t1", name="Migrate the servers", notes=TREATMENT_NOTES, cost=40000)
    t["lef"]["vuln"].update(min=0.01, ml=0.03, max=0.05)            # planted: a fraction, not a percent
    resp = t["primary"]["response"]
    t["primary"]["response"].update(min=resp["min"] / 4, ml=resp["ml"] / 4, max=resp["max"] / 4)  # planted: unexplained
    doc["states"].append(t)
    assert client.put(f"/api/analyses/{aid}", json=doc).status_code == 200
    return aid


def test_review_and_report_on_tr6(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")
    recorded: dict[str, dict] = {"review": {}, "report": {}}
    real_call = agent_client.call_task

    def call(task, payload):
        if task in REPLAYED:
            title = payload["risk"]["title"]
            return TaskResult(output=copy.deepcopy(RECORDED[task][title]), model="recorded",
                              prompt_version=f"{task}.v1", input_tokens=0, output_tokens=0)
        res = real_call(task, payload)
        recorded[task]["TR-6"] = copy.deepcopy(res.output)
        return res

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    aid = tr6_analysis(client)
    problems = []

    assert client.post(f"/api/agent/analyses/{aid}/review").status_code == 202
    view = client.get(f"/api/analyses/{aid}/agent").json()
    run = view["runs"][0]
    if run["status"] != "succeeded":
        problems.append(f"review run {run['status']}: {run['error']}")
    else:
        findings = view["review"]["effective"]["findings"]
        print("\nReview:", view["review"]["effective"]["summary"])
        for f in findings:
            print(f"  {f['kind']:20} {f['state_id']} {f['factor']}: {f['message']}")
        if not any(f["state_id"] == "t1" and f["factor"] == "primary.response" for f in findings):
            problems.append("review missed the unexplained change to primary loss response in the treatment")
        if not any(f["state_id"] == "t1" and f["factor"] == "vuln" and f["kind"] in ("unit_mistake", "other")
                   for f in findings):
            problems.append("review missed the vulnerability entered as a fraction in the treatment")

    rid = client.post(f"/api/analyses/{aid}/runs").json()["id"]
    assert client.post(f"/api/agent/analyses/{aid}/runs/{rid}/report").status_code == 202
    view = client.get(f"/api/analyses/{aid}/agent").json()
    run = view["runs"][0]
    tokens = sum(r["inputTokens"] for r in view["runs"]), sum(r["outputTokens"] for r in view["runs"])
    if run["status"] != "succeeded":
        problems.append(f"report run {run['status']}: {run['error']}")
    else:
        rep = view["reports"][rid]
        print("\nLeadership summary:\n" + rep["effective"]["leadershipSummary"])
        print("\nException justification:\n" + (rep["effective"]["exceptionJustification"] or "(none)"))
        if rep["numberCheck"]:
            problems.append(f"report numbers not in the run: {rep['numberCheck']}")
        if not rep["effective"]["exceptionJustification"]:
            problems.append("no exception justification, with a treatment to compare")

    print(f"\nTokens (review and report): {tokens[0]:,} in, {tokens[1]:,} out.")
    if os.environ.get("RECORD_DIR"):
        out = Path(os.environ["RECORD_DIR"]) / "reporting_recorded.json"
        out.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded model outputs to {out}")
    assert not problems, "\n".join(problems)
