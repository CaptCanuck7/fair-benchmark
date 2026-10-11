"""Replay recorded scenario and vectors output through the API (no network).

fixtures/scenario_recorded.json holds the agent's outputs from a live run of
tests/test_live_eval_scenarios.py (refresh it with RECORD_DIR). Replaying them
checks the section 14 expectations for scenarios and vectors on every run.
"""

import json

import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER
from test_live_eval_scenarios import QUALIFYING, WITH_EXPLOIT_PATHS

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.routers import agent as agent_router
from app.routers import register as register_router

RECORDED = {**json.loads((FIXTURES / "intake_recorded.json").read_text(encoding="utf-8")),
            **json.loads((FIXTURES / "scenario_recorded.json").read_text(encoding="utf-8"))}
ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def drafted(client, monkeypatch):
    def call(task, payload):
        return TaskResult(output=RECORDED[task][payload["risk"]["title"]], model="recorded",
                          prompt_version=f"{task}.v1", input_tokens=0, output_tokens=0)

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})
    out = {}
    for rid in QUALIFYING:
        assert client.post(f"/api/agent/risks/{rid}/scenario").status_code == 202
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        assert client.post(f"/api/agent/risks/{rid}/vectors").status_code == 202
        out[rid] = client.get(f"/api/register/risks/{rid}").json()
    return out


def test_tr6_is_a_malicious_external_confidentiality_scenario(drafted):
    s = drafted["TR-6"]["scenario"]["effective"]
    assert (s["threat_type"], s["effect"]) == ("Malicious, external", "Confidentiality")


def test_tr12_is_a_failure_with_failure_paths(drafted):
    s, v = drafted["TR-12"]["scenario"]["effective"], drafted["TR-12"]["vectors"]["effective"]
    assert s["threat_type"].startswith("Failure") and s["effect"] == "Availability"
    assert v["kind"] == "failure_paths" and all(p["what_fails"] for p in v["paths"])


def test_tr10_proposes_the_availability_split(drafted):
    alts = drafted["TR-10"]["scenario"]["effective"]["alternatives"]
    assert any(a["effect"] == "Availability" and a["split_reason"] == "threat_type_or_effect_differs" for a in alts)


@pytest.mark.parametrize("rid", QUALIFYING)
def test_vectors_follow_the_register(drafted, rid):
    v = drafted[rid]["vectors"]
    want = "from_register" if rid in WITH_EXPLOIT_PATHS else "agent_drafted"
    assert {p["origin"] for p in v["effective"]["paths"]} == {want}
    assert drafted[rid]["vectorsStale"] is False
    assert all(not p["steps"][0]["text"][:2].rstrip(".").isdigit() for p in v["effective"]["paths"])
