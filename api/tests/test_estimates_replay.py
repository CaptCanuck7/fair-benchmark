"""Replay recorded estimates through the API (no network).

fixtures/estimates_recorded.json holds the agent's estimates from a live run of
tests/test_live_eval_estimates.py (refresh it with RECORD_DIR). Replaying them
checks the section 9.6 rules, the TR-7 expectation, and the milestone 6 path:
an analysis created from TR-6 runs and carries provenance.
"""

import copy
import json

import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER
from test_live_eval_estimates import estimate_problems, required_for, zero_logins_is_weak
from test_live_eval_scenarios import QUALIFYING

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.routers import agent as agent_router
from app.routers import register as register_router

RECORDED = {}
for name in ("intake_recorded.json", "scenario_recorded.json", "evidence_recorded.json", "estimates_recorded.json"):
    RECORDED.update(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def estimated(client, monkeypatch):
    def call(task, payload):
        # The pipeline turns new requests into stored ones in place, so hand it a copy.
        return TaskResult(output=copy.deepcopy(RECORDED[task][payload["risk"]["title"]]), model="recorded",
                          prompt_version=f"{task}.v1", input_tokens=0, output_tokens=0)

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})
    out = {}
    for rid in QUALIFYING:
        client.post(f"/api/agent/risks/{rid}/scenario")
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        assert client.post(f"/api/agent/risks/{rid}/evidence").status_code == 202
        assert client.post(f"/api/agent/risks/{rid}/estimates").status_code == 202
        out[rid] = client.get(f"/api/register/risks/{rid}").json()
    return out


@pytest.mark.parametrize("rid", QUALIFYING)
def test_recorded_estimates_meet_the_rules(estimated, rid):
    d = estimated[rid]
    assert d["runs"][0]["task"] == "estimates" and d["runs"][0]["status"] == "succeeded"
    raw = RECORDED["estimates"][d["title"]]
    evidence = {e["id"]: e for e in d["evidence"]}
    assert estimate_problems(rid, raw, evidence, required_for(raw["method"])) == []
    # The anchoring guard: nothing revealed yet, so no agent range in the response.
    assert all(f["agent"] is None and not f["revealed"] for f in d["estimates"]["factors"])
    # Every unestimated factor points to a stored data request.
    request_ids = {r["id"] for r in d["dataRequests"]}
    for f in d["estimates"]["factors"]:
        if f["unestimated"]:
            assert f["unestimated"]["dataRequestId"] in request_ids


def test_tr7_says_zero_confirmed_logins_is_weak_evidence(estimated):
    raw = RECORDED["estimates"][estimated["TR-7"]["title"]]
    assert zero_logins_is_weak(" ".join(e["rationale"] for e in raw["estimates"]) + " " + raw["method"]["reason"])


def test_tr6_analysis_runs_with_provenance(client, estimated):
    est = estimated["TR-6"]["estimates"]
    picked = [f["factor"] for f in est["factors"] if f["status"] == "estimated"]
    for factor in picked:
        assert client.post(f"/api/register/risks/TR-6/estimates/{factor}/reveal",
                           json={"analystRange": None}).status_code == 200
        assert client.put(f"/api/register/risks/TR-6/estimates/{factor}", json={"choice": "agent"}).status_code == 200
    res = client.post("/api/register/risks/TR-6/create-analysis")
    assert res.status_code == 201
    aid = res.json()["analysisId"]
    assert sorted(res.json()["factorsPushed"]) == sorted(picked)

    run = client.post(f"/api/analyses/{aid}/runs")
    assert run.status_code in (200, 201), run.text
    assert run.json()["results"]["states"][0]["meanAnnualLoss"] > 0

    prov = client.get(f"/api/analyses/{aid}/provenance").json()
    assert prov["linked"] and prov["riskId"] == "TR-6"
    assert {p["factor"] for p in prov["factors"]} == set(picked)
    assert all(p["origin"] == "agent" and p["evidence"] for p in prov["factors"])
