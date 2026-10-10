"""Replay recorded model outputs through the intake pipeline (no network).

fixtures/intake_recorded.json holds the agent's outputs from a live run of
tests/test_live_eval.py on the test register (refresh it with RECORD_DIR).
Replaying them checks the section 14 expectations for quality, triage and
condition type on real model output, on every test run.
"""

import json

import pytest
from conftest import FIXTURES
from test_live_eval import EXPECTED, EXPECTED_GAPS, EXPECTED_SCORES, REGISTER

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.routers import agent as agent_router
from app.routers import register as register_router

RECORDED = json.loads((FIXTURES / "intake_recorded.json").read_text(encoding="utf-8"))
ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def replay(client, monkeypatch):
    def call(task, payload):
        output = RECORDED[task][payload["risk"]["title"]]
        return TaskResult(output=output, model="recorded", prompt_version=f"{task}.v1",
                          input_tokens=0, output_tokens=0)

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    res = client.post("/api/register/import", files={"file": ("register.xlsx", REGISTER.read_bytes(),
                                                              "application/octet-stream")})
    assert res.status_code == 201
    return {r["riskId"]: r for r in client.get("/api/register/risks").json()}


@pytest.mark.parametrize("rid", list(EXPECTED))
def test_section_14_intake_expectations(client, replay, rid):
    quality, triage, types = EXPECTED[rid]
    r = replay[rid]
    assert r["quality"] == quality
    assert r["triage"] == triage
    if types is not None:
        assert r["classification"] in types
    else:
        assert r["classification"] is None
    detail = client.get(f"/api/register/risks/{rid}").json()
    if triage:
        assert detail["intake"]["triage"]["effective"]["score"] == EXPECTED_SCORES[rid]
        assert detail["intake"]["triage"]["effective"]["reason"]
    if rid in EXPECTED_GAPS:
        q = detail["intake"]["quality"]["effective"]
        assert EXPECTED_GAPS[rid] <= {g["field"] for g in q["gaps"]}
        assert q["questions"]
        assert detail["intake"]["triage"] is None and detail["intake"]["classification"] is None
