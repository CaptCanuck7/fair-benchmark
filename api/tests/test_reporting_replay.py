"""Replay recorded review and report output through the API (no network).

fixtures/reporting_recorded.json holds the agent's review and report for TR-6
from a live run of tests/test_live_eval_reporting.py (refresh it with
RECORD_DIR). The simulation is seeded, so the replayed run reproduces the
numbers the report quotes, and the number check must pass on it again.
"""

import copy
import json

import pytest
from conftest import FIXTURES
from test_live_eval_reporting import RECORDED, REPLAYED, tr6_analysis

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.routers import agent as agent_router
from app.routers import register as register_router

LIVE = json.loads((FIXTURES / "reporting_recorded.json").read_text(encoding="utf-8"))
ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def analysis(client, monkeypatch) -> str:
    def call(task, payload):
        out = RECORDED[task][payload["risk"]["title"]] if task in REPLAYED else LIVE[task]["TR-6"]
        return TaskResult(output=copy.deepcopy(out), model="recorded", prompt_version=f"{task}.v1",
                          input_tokens=0, output_tokens=0)

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    return tr6_analysis(client)


def test_recorded_review_names_both_planted_problems(client, analysis):
    assert client.post(f"/api/agent/analyses/{analysis}/review").status_code == 202
    findings = client.get(f"/api/analyses/{analysis}/agent").json()["review"]["effective"]["findings"]
    hits = {(f["state_id"], f["factor"]) for f in findings}
    assert ("t1", "primary.response") in hits and ("t1", "vuln") in hits


def test_recorded_report_passes_the_number_check_on_a_rerun(client, analysis):
    rid = client.post(f"/api/analyses/{analysis}/runs").json()["id"]
    assert client.post(f"/api/agent/analyses/{analysis}/runs/{rid}/report").status_code == 202
    view = client.get(f"/api/analyses/{analysis}/agent").json()
    assert view["runs"][0]["status"] == "succeeded", view["runs"][0]["error"]
    rep = view["reports"][rid]
    assert rep["numberCheck"] == [] and rep["effective"]["residualName"] == "Migrate the servers"
    assert rep["effective"]["exceptionJustification"]


def test_one_altered_figure_in_the_recorded_report_is_discarded(client, analysis, monkeypatch):
    text = LIVE["report"]["TR-6"]["leadership_summary"]
    altered = {**LIVE["report"]["TR-6"], "leadership_summary": text.replace("$291K", "$301K", 1)}
    assert altered["leadership_summary"] != text
    monkeypatch.setitem(LIVE["report"], "TR-6", altered)
    rid = client.post(f"/api/analyses/{analysis}/runs").json()["id"]
    client.post(f"/api/agent/analyses/{analysis}/runs/{rid}/report")
    view = client.get(f"/api/analyses/{analysis}/agent").json()
    assert view["reports"] == {} and "$301K" in view["runs"][0]["error"]
