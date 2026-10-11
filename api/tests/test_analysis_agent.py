"""Task 7 through the API: input review, report drafts and the number check.

The agent is faked and jobs run inline. The report fake writes its text from
the figures it is sent, as the real prompt asks.
"""

import copy

import pytest
from test_api import create, product_x_doc

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult
from app.config import settings
from app.db import SessionLocal
from app.models import AgentRunRow, AnalysisDraftRow, RunRow
from app.report_check import money, pct, unmatched_numbers
from app.routers import agent as agent_router

ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


class FakeAgent:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.alter: str | None = None  # a figure to replace with a number not in the run

    def __call__(self, task, payload):
        self.calls.append((task, copy.deepcopy(payload)))
        if task == "review":
            s1 = payload["states"][1]
            out = {"summary": "One treatment change isn't explained.",
                   "findings": [{"kind": "unexplained_change", "state_id": s1["id"],
                                 "factor": s1["changes"][0]["factor"], "message": "The notes don't explain it.",
                                 "suggestion": None, "evidence_ids": []}]}
        else:
            base, opt = payload["options"][0], payload["options"][1]
            f = base["figures"]
            text = (f"An average year costs {f['Average annual loss']} and a bad year "
                    f"{f['Annual loss in a bad year (90th percentile)']}. Some loss happens in "
                    f"{f['Chance of any loss in a year']} of years. {opt['name']} brings the average to "
                    f"{opt['figures']['Average annual loss']}.")
            if self.alter:
                text = text.replace(f["Average annual loss"], self.alter)
            just = (f"{opt['name']} costs {opt['figures']['Annual cost of this option']} a year and "
                    f"{opt['compared_with_current']['Net benefit']}.")
            out = {"leadership_summary": text,
                   "exception_justification": just if payload["residual_state_id"] else None}
        return TaskResult(output=out, model="fake", prompt_version=f"{task}.v1", input_tokens=5, output_tokens=7)


@pytest.fixture
def fake(monkeypatch) -> FakeAgent:
    f = FakeAgent()
    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", f)
    monkeypatch.setattr(agent_router, "fetch_agent_status", lambda: ON)
    monkeypatch.setattr(settings, "analyst_name", "Test Analyst")
    return f


def with_treatment() -> dict:
    doc = product_x_doc()
    base = doc["states"][0]
    base["lef"]["tef"]["src"] = "Telemetry count.\nAgent-drafted, approved by Test Analyst on 2026-10-11."
    t = copy.deepcopy(base)
    t.update(id="t1", name="Patch faster", notes="Patch within 7 days.", cost=50000)
    t["lef"]["vuln"].update(min=1, ml=4, max=10)
    doc["states"].append(t)
    return doc


@pytest.fixture
def analysis(client) -> dict:
    return create(client, with_treatment())


def view(client, aid) -> dict:
    r = client.get(f"/api/analyses/{aid}/agent")
    assert r.status_code == 200, r.text
    return r.json()


def run_sim(client, aid) -> str:
    r = client.post(f"/api/analyses/{aid}/runs")
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- the number check

def stored_run(client, aid) -> RunRow:
    rid = run_sim(client, aid)
    with SessionLocal() as s:
        return s.get(RunRow, rid)


def test_number_check_accepts_copied_figures_and_rejects_one_altered(client, analysis):
    run = stored_run(client, analysis["id"])
    s0, s1 = run.results["states"]
    good = (f"An average year costs {money(s0['meanAnnualLoss'])}, a bad year {money(s0['p90'])} (the 90th "
            f"percentile, P90), and some loss happens in {pct(s0['chanceAnyLoss'])} of years. Patch faster costs "
            f"{money(50000)} a year. Simulated over 10,000 years in 2026, with two options.")
    names = [run.document_snapshot["title"], "Current state", "Patch faster"]
    assert unmatched_numbers([good], run.results, run.document_snapshot, names) == []

    altered = good.replace(money(s0["p90"]), "$9.99M")
    assert unmatched_numbers([good, altered], run.results, run.document_snapshot, names) == ["$9.99M"]


def test_number_check_rounding_and_formats(client, analysis):
    run = stored_run(client, analysis["id"])
    mean = run.results["states"][0]["meanAnnualLoss"]
    doc = run.document_snapshot
    ok = [f"${mean / 1e3:,.0f}K", f"${mean:,.0f}", f"{mean / 1e6:.1f} million dollars", "2 to 6 attempts a year",
          "a 60% chance", "8 percent"]
    for text in ok:
        assert unmatched_numbers([text], run.results, doc) == [], text
    assert unmatched_numbers([f"${mean / 1e3 + 3:,.0f}K"], run.results, doc) == [f"${mean / 1e3 + 3:,.0f}K"]
    assert unmatched_numbers(["about 37 events"], run.results, doc) == ["37"]


# ---------------------------------------------------------------- input review

def test_review_reads_the_document_and_stores_findings(client, fake, analysis):
    aid = analysis["id"]
    r = client.post(f"/api/agent/analyses/{aid}/review")
    assert r.status_code == 202, r.text
    task, payload = fake.calls[-1]
    assert task == "review"
    base, treat = payload["states"]
    assert base["baseline"] and not treat["baseline"]
    assert [c["factor"] for c in treat["changes"]] == ["vuln"]
    tef = next(f for f in base["factors"] if f["factor"] == "tef")
    assert tef["rationale"] == "Telemetry count." and "Test Analyst" not in str(payload)
    assert payload["evidence"] == []

    v = view(client, aid)
    assert v["busy"] is False and v["runs"][0]["task"] == "review" and v["runs"][0]["status"] == "succeeded"
    review = v["review"]
    assert review["kind"] == "review" and review["status"] == "drafted" and review["stale"] is False
    assert review["effective"]["findings"][0]["kind"] == "unexplained_change"

    # Findings never block a run; changing the inputs makes the review stale.
    run_sim(client, aid)
    doc = client.get(f"/api/analyses/{aid}").json()
    doc["states"][0]["lef"]["tef"]["ml"] = 3
    assert client.put(f"/api/analyses/{aid}", json=doc).status_code == 200
    assert view(client, aid)["review"]["stale"] is True


def test_review_sends_post_run_checks_for_current_inputs(client, fake, analysis):
    aid = analysis["id"]
    run_sim(client, aid)
    client.post(f"/api/agent/analyses/{aid}/review")
    checks = fake.calls[-1][1]["checks"]
    assert checks and {c["state_id"] for c in checks} >= {"t1"}


def test_review_can_be_approved_or_rejected_not_edited(client, fake, analysis):
    aid = analysis["id"]
    client.post(f"/api/agent/analyses/{aid}/review")
    did = view(client, aid)["review"]["id"]
    r = client.put(f"/api/analysis-drafts/{did}", json={"action": "edit",
                                                          "payload": {"leadershipSummary": "x"}})
    assert r.status_code == 409
    r = client.put(f"/api/analysis-drafts/{did}", json={"action": "reject"})
    assert r.json()["review"]["status"] == "rejected" and r.json()["review"]["reviewer"] == "Test Analyst"


# ---------------------------------------------------------------- reports

def test_report_drafts_from_the_stored_run(client, fake, analysis):
    aid = analysis["id"]
    rid = run_sim(client, aid)
    r = client.post(f"/api/agent/analyses/{aid}/runs/{rid}/report")
    assert r.status_code == 202, r.text
    task, payload = fake.calls[-1]
    assert task == "report" and payload["residual_state_id"] == "t1"
    assert payload["run"]["simulated_years"] == "10,000"
    assert payload["options"][1]["compared_with_current"]["Annual cost"] == "$50K"

    rep = view(client, aid)["reports"][rid]
    assert rep["status"] == "drafted" and rep["numberCheck"] == []
    assert rep["effective"]["residualName"] == "Patch faster"
    assert "$50K" in rep["effective"]["exceptionJustification"]

    # An analyst's edit is kept beside the draft; numbers not in the run are flagged, not blocked.
    edit = {"leadershipSummary": rep["payload"]["leadershipSummary"] + " Roughly $7.77M in the worst case.",
            "exceptionJustification": rep["payload"]["exceptionJustification"]}
    r = client.put(f"/api/analysis-drafts/{rep['id']}", json={"action": "edit", "payload": edit})
    rep = r.json()["reports"][rid]
    assert rep["status"] == "edited" and rep["numberCheck"] == ["$7.77M"]
    assert rep["payload"]["leadershipSummary"] != rep["effective"]["leadershipSummary"]
    r = client.put(f"/api/analysis-drafts/{rep['id']}", json={"action": "approve"})
    assert r.json()["reports"][rid]["status"] == "edited"


def test_a_report_with_an_altered_number_is_discarded(client, fake, analysis):
    aid = analysis["id"]
    rid = run_sim(client, aid)
    fake.alter = "$4.56M"
    client.post(f"/api/agent/analyses/{aid}/runs/{rid}/report")
    v = view(client, aid)
    assert v["reports"] == {}
    run = v["runs"][0]
    assert run["status"] == "failed" and "$4.56M" in run["error"] and "discarded" in run["error"]


def test_report_without_a_treatment_has_no_justification(client, fake):
    aid = create(client, product_x_doc())["id"]
    rid = run_sim(client, aid)
    fake_payload_options = None

    def one_option(task, payload):
        nonlocal fake_payload_options
        fake_payload_options = payload["options"]
        f = payload["options"][0]["figures"]
        return TaskResult(output={"leadership_summary": f"An average year costs {f['Average annual loss']}.",
                                  "exception_justification": None},
                          model="fake", prompt_version="report.v1", input_tokens=1, output_tokens=1)

    agent_client.call_task = one_option  # restored by the fixture's monkeypatch
    client.post(f"/api/agent/analyses/{aid}/runs/{rid}/report")
    rep = view(client, aid)["reports"][rid]
    assert len(fake_payload_options) == 1
    assert rep["effective"]["exceptionJustification"] is None and rep["effective"]["residualStateId"] is None


# ---------------------------------------------------------------- guards

def test_one_job_at_a_time_and_agent_off(client, fake, analysis, monkeypatch):
    aid = analysis["id"]
    with SessionLocal() as s:
        s.add(AgentRunRow(id="busy1", analysis_id=aid, task="review", status="running", started_at="2026-10-11"))
        s.commit()
    assert client.post(f"/api/agent/analyses/{aid}/review").status_code == 409
    monkeypatch.setattr(agent_router, "fetch_agent_status",
                        lambda: {**ON, "configured": False, "reason": "No API key."})
    r = client.post(f"/api/agent/analyses/{aid}/review")
    assert r.status_code == 503 and r.json()["detail"] == "No API key."


def test_report_needs_this_analysis_run(client, fake, analysis):
    other = create(client, product_x_doc())["id"]
    rid = run_sim(client, other)
    assert client.post(f"/api/agent/analyses/{analysis['id']}/runs/{rid}/report").status_code == 404
    assert client.post("/api/agent/analyses/nope/review").status_code == 404


def test_deleting_the_analysis_removes_its_drafts(client, fake, analysis):
    aid = analysis["id"]
    client.post(f"/api/agent/analyses/{aid}/review")
    assert client.delete(f"/api/analyses/{aid}").status_code == 204
    with SessionLocal() as s:
        assert s.query(AnalysisDraftRow).count() == 0
