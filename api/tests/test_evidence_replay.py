"""Replay recorded evidence output through the API (no network).

fixtures/evidence_recorded.json holds the agent's evidence results from a live
run of tests/test_live_eval_evidence.py (refresh it with RECORD_DIR). Replaying
them checks the section 14 evidence expectations on every test run.
"""

import json

import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER
from test_live_eval_evidence import MUST_CITE
from test_live_eval_scenarios import QUALIFYING

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.routers import agent as agent_router
from app.routers import register as register_router

RECORDED = {}
for name in ("intake_recorded.json", "scenario_recorded.json", "evidence_recorded.json"):
    RECORDED.update(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}
GROUPS = {"frequency", "susceptibility", "primary", "secondary"}


@pytest.fixture
def gathered(client, monkeypatch):
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
        client.post(f"/api/agent/risks/{rid}/scenario")
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        assert client.post(f"/api/agent/risks/{rid}/evidence").status_code == 202
        out[rid] = client.get(f"/api/register/risks/{rid}").json()
    return out


@pytest.mark.parametrize("rid", QUALIFYING)
def test_every_group_has_evidence_or_a_request(gathered, rid):
    d = gathered[rid]
    covered = {g for e in d["evidence"] for g in e["groups"]} | {g for r in d["dataRequests"] for g in r["groups"]}
    assert covered == GROUPS
    assert d["evidenceRun"]["rejected"] == []


@pytest.mark.parametrize("rid", sorted(MUST_CITE))
def test_section_14_records_are_cited(gathered, rid):
    cites = [e["citation"] for e in gathered[rid]["evidence"]]
    for frag in MUST_CITE[rid]:
        assert any(frag in c for c in cites), frag


def test_tr6_finds_the_record_count(gathered):
    assert any(e["value"] == 410000 for e in gathered["TR-6"]["evidence"])


def test_tr9_requests_frequency_data(gathered):
    assert any("frequency" in r["groups"] for r in gathered["TR-9"]["dataRequests"])


def test_tr11_and_tr14_request_record_counts(gathered):
    assert any(r["team"] == "Asset Management" and "record" in r["question"].lower()
               for r in gathered["TR-11"]["dataRequests"])
    assert any("record" in r["question"].lower() for r in gathered["TR-14"]["dataRequests"])


def test_tr12_made_no_cve_lookups(gathered):
    notes = gathered["TR-12"]["evidenceRun"]["notes"]
    assert notes["cveLookupsOffered"] is False and notes["cveLookupsMade"] == 0
