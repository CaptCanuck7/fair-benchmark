"""Evidence gathering, data requests, settings and the reference library, through the API.

The agent is faked (test_intake_pipeline.FakeAgent) and jobs run inline.
"""

import json

import pytest
from test_drafts_workflow import detail, review, scenario_for, start
from test_intake_pipeline import FakeAgent, import_register

from app import agent_client, agent_pipeline, app_settings
from app.config import settings
from app.db import SessionLocal
from app.routers import agent as agent_router
from app.routers import library as library_router
from app.routers import register as register_router

ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def fake(monkeypatch) -> FakeAgent:
    f = FakeAgent()
    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", f)
    for module in (register_router, agent_router, library_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    monkeypatch.setattr(settings, "analyst_name", "Test Analyst")
    return f


def approved_scenario(client, rid="TR-6"):
    s = scenario_for(client, rid)
    review(client, s["id"], "approve")


# ---------------------------------------------------------------- evidence

def test_evidence_waits_for_an_approved_scenario(client, fake):
    import_register(client)
    res = start(client, "TR-6", "evidence")
    assert res.status_code == 409 and "Draft and approve the scenario first" in res.json()["detail"]
    s = scenario_for(client, "TR-6")
    assert start(client, "TR-6", "evidence").status_code == 409
    review(client, s["id"], "approve")
    assert detail(client, "TR-6")["blocked"]["evidence"] is None
    assert start(client, "TR-6", "evidence").status_code == 202


def test_evidence_is_stored_grouped_and_flagged(client, fake):
    import_register(client)
    approved_scenario(client)
    start(client, "TR-6", "evidence")
    d = detail(client, "TR-6")
    items = {e["citation"]: e for e in d["evidence"]}
    assert set(items) == {"Incident History INC-2026-021", "https://www.verizon.com/old"}
    assert items["Incident History INC-2026-021"]["groups"] == ["frequency"]
    assert items["https://www.verizon.com/old"]["groups"] == ["secondary"] and items["https://www.verizon.com/old"]["stale"]
    assert [r["team"] for r in d["dataRequests"]] == ["Vulnerability Management"]
    assert d["dataRequests"][0]["groups"] == ["susceptibility"] and d["dataRequests"][0]["status"] == "open"
    run = d["evidenceRun"]
    assert run["toolCalls"] == 4 and run["rejected"][0]["citation"] == "Made up"
    assert run["notes"]["cveLookupsMade"] == 1

    # What the agent was sent: the approved scenario, the classification and a run ID for the outbound log.
    sent = [p for t, p in fake.calls if t == "evidence"][-1]
    assert sent["agent_run_id"] == run["id"] and sent["scenario"]["threat_type"] == "Malicious, external"
    assert sent["classification"]["primary_type"] == "missing_control" and "basedOn" not in sent["scenario"]


def test_a_new_run_replaces_items_but_keeps_answers(client, fake):
    import_register(client)
    approved_scenario(client)
    start(client, "TR-6", "evidence")
    req_id = detail(client, "TR-6")["dataRequests"][0]["id"]
    client.put(f"/api/data-requests/{req_id}", json={"answer": "Last tested March 2026; no findings."})
    start(client, "TR-6", "evidence")
    d = detail(client, "TR-6")
    summaries = [e["summary"] for e in d["evidence"] if e["origin"] == "internal" and not e["fromDataRequest"]]
    assert summaries == ["An attempt, run 2."]
    statuses = sorted(r["status"] for r in d["dataRequests"])
    assert statuses == ["answered", "open"]  # the old answered request plus the new run's open one
    assert any(e["fromDataRequest"] == req_id for e in d["evidence"])


def test_answering_a_request_creates_cited_evidence(client, fake):
    import_register(client)
    approved_scenario(client)
    start(client, "TR-6", "evidence")
    req = detail(client, "TR-6")["dataRequests"][0]
    res = client.put(f"/api/data-requests/{req['id']}", json={"answer": "Penetration tested in March 2026."})
    assert res.status_code == 200
    answered = next(r for r in res.json()["dataRequests"] if r["id"] == req["id"])
    assert answered["status"] == "answered" and answered["answeredBy"] == "Test Analyst"
    item = next(e for e in res.json()["evidence"] if e["fromDataRequest"] == req["id"])
    assert item["citation"].startswith("Data request answered by Vulnerability Management on ")
    assert (item["origin"], item["sourceType"], item["factors"]) == ("internal", "data_request", ["vuln"])
    assert "Penetration tested in March 2026." in item["summary"]

    # Answering again replaces the answer and its evidence item.
    res = client.put(f"/api/data-requests/{req['id']}", json={"answer": "Corrected: tested in April 2026."})
    mine = [e for e in res.json()["evidence"] if e["fromDataRequest"] == req["id"]]
    assert len(mine) == 1 and "April 2026" in mine[0]["summary"]


def test_answer_validation(client, fake):
    import_register(client)
    approved_scenario(client)
    start(client, "TR-6", "evidence")
    req_id = detail(client, "TR-6")["dataRequests"][0]["id"]
    assert client.put(f"/api/data-requests/{req_id}", json={"answer": "   "}).status_code == 422
    assert client.put("/api/data-requests/9999", json={"answer": "x"}).status_code == 404


# ---------------------------------------------------------------- settings

def test_settings_round_trip_and_validation(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "triage_min_score", settings.triage_min_score)  # restored after the test
    res = client.put("/api/settings", json={"analystName": "  Dana Analyst ", "triageMinScore": 8,
                                            "externalEnabled": False,
                                            "extraDomains": ["https://www.CIS.example.org/x", "sans.org"],
                                            "removedDomains": ["ibm.com"]})
    assert res.status_code == 200
    body = res.json()
    assert body == {"analystName": "Dana Analyst", "triageMinScore": 8, "externalEnabled": False,
                    "extraDomains": ["sans.org", "www.cis.example.org"], "removedDomains": ["ibm.com"]}
    assert (settings.analyst_name, settings.triage_min_score) == ("Dana Analyst", 8)
    cfg = client.get("/internal/guard/agent-config").json()
    assert cfg == {"externalEnabled": False, "extraDomains": ["sans.org", "www.cis.example.org"],
                   "removedDomains": ["ibm.com"]}
    for bad, path in (({"triageMinScore": 0}, "triageMinScore"), ({"triageMinScore": "6"}, "triageMinScore"),
                      ({"extraDomains": ["not a domain"]}, "extraDomains"), ({"externalEnabled": "yes"}, "externalEnabled")):
        r = client.put("/api/settings", json=bad)
        assert r.status_code == 422 and r.json()["errors"][0]["path"] == path, bad
    assert client.put("/api/settings", json={"colour": "blue"}).status_code == 422
    # Back to the .env values.
    client.put("/api/settings", json={"externalEnabled": None})
    assert client.get("/api/settings").json()["externalEnabled"] is None


def test_the_analyst_name_from_settings_is_recorded_on_reviews(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "analyst_name", "")
    client.put("/api/settings", json={"analystName": "Robin Reviewer"})
    import_register(client)
    s = scenario_for(client, "TR-7")
    assert review(client, s["id"], "approve").json()["scenario"]["reviewer"] == "Robin Reviewer"


# ---------------------------------------------------------------- reference library

ENTRY = {"metric": "Average cost of a data breach", "value": 4880000, "unit": "USD", "segment": "Global",
         "source": "IBM Cost of a Data Breach Report", "edition": "2024",
         "url": "https://www.ibm.com/reports/data-breach", "page": "12", "quote": "USD 4.88 million"}


def test_library_starts_empty_and_takes_manual_entries(client, fake):
    assert client.get("/api/library").json() == []
    res = client.post("/api/library", json=ENTRY)
    assert res.status_code == 201
    e = res.json()
    assert e["status"] == "approved" and e["approvedBy"] == "Test Analyst"
    assert e["citation"] == "IBM Cost of a Data Breach Report 2024, p. 12: https://www.ibm.com/reports/data-breach"
    assert client.post("/api/library", json={**ENTRY, "url": "not a url"}).status_code == 422


def test_library_refresh_proposes_and_analysts_review(client, fake):
    res = client.post("/api/library/refresh")
    assert res.status_code == 202
    run = client.get(f"/api/agent/runs/{res.json()['runId']}").json()
    assert run["status"] == "succeeded" and run["task"] == "library"
    proposed = client.get("/api/library?status=proposed").json()
    assert [p["metric"] for p in proposed] == ["Cost per record"] and proposed[0]["approvedBy"] is None

    # Proposed entries aren't evidence until approved.
    assert client.get("/internal/library?q=record").json() == []
    pid = proposed[0]["id"]
    assert client.put(f"/api/library/{pid}", json={"action": "approve"}).json()["status"] == "approved"
    found = client.get("/internal/library?q=cost record").json()
    assert [f["id"] for f in found] == [pid]
    assert client.put(f"/api/library/{pid}", json={"action": "reject"}).json()["status"] == "rejected"
    assert client.get("/internal/library?q=record").json() == []

    # A second refresh doesn't propose the same figure again.
    client.post("/api/library/refresh")
    assert len(client.get("/api/library").json()) == 1


def test_library_edit_and_refresh_rules(client, fake, monkeypatch):
    e = client.post("/api/library", json=ENTRY).json()
    edited = client.put(f"/api/library/{e['id']}", json={"action": "edit", "entry": {**ENTRY, "value": 4900000}})
    assert edited.json()["value"] == 4900000
    assert client.put(f"/api/library/{e['id']}", json={"action": "edit"}).status_code == 422
    monkeypatch.setattr(library_router, "fetch_agent_status", lambda: {**ON, "externalEnabled": False})
    assert client.post("/api/library/refresh").status_code == 409


def test_library_seed_file(tmp_path, client):
    (tmp_path / "reference_library.json").write_text(json.dumps({"entries": [{**ENTRY, "approved_by": "seed"}]}))
    with SessionLocal() as s:
        assert library_router.seed_library(s, tmp_path) == 1
        assert library_router.seed_library(s, tmp_path) == 0  # only into an empty table
    assert client.get("/api/library").json()[0]["approvedBy"] == "seed"


def test_settings_survive_through_apply(client):
    client.put("/api/settings", json={"triageMinScore": 9})
    settings.triage_min_score = 6
    with SessionLocal() as s:
        app_settings.apply(s)
    assert settings.triage_min_score == 9
    client.put("/api/settings", json={"triageMinScore": 6})


# ---------------------------------------------------------------- AGENT_FIXES.md fix 6: value checks

MARKER = "SRC-FIELD-MARKER-7731"
SOURCE = {"Incident ID": "INC-2026-021", "Attempts": 1, "Notes": f"One attempt. {MARKER}"}


@pytest.fixture
def checked(fake, monkeypatch):
    """The fake's evidence with the agent's value check: the incident's value
    is found in its record; the old report is a web item, not checked."""
    def call(task, payload):
        res = fake(task, payload)
        if task == "evidence":
            inc, web = res.output["items"]
            inc.update(value_check="found", source_fields=SOURCE)
            web.update(value_check="not_checked", source_fields=None)
        return res

    monkeypatch.setattr(agent_client, "call_task", call)
    return fake


def gathered(client) -> dict:
    import_register(client)
    review(client, scenario_for(client, "TR-6")["id"], "approve")
    assert start(client, "TR-6", "evidence").status_code == 202
    return detail(client, "TR-6")


def test_value_checks_and_source_records_are_stored_and_shown(client, checked):
    ev = {e["citation"]: e for e in gathered(client)["evidence"]}
    inc, web = ev["Incident History INC-2026-021"], ev["https://www.verizon.com/old"]
    assert (inc["valueCheck"], inc["sourceFields"]) == ("found", SOURCE)
    assert (web["valueCheck"], web["sourceFields"]) == ("not_checked", None)


def test_a_not_found_value_is_kept(client, fake, monkeypatch):
    def call(task, payload):
        res = fake(task, payload)
        if task == "evidence":
            for item in res.output["items"]:
                item.update(value_check="not_found", source_fields={"Attempts": 3})
        return res

    monkeypatch.setattr(agent_client, "call_task", call)
    d = gathered(client)
    assert len(d["evidence"]) == 2 and {e["valueCheck"] for e in d["evidence"]} == {"not_found"}


def test_answered_requests_are_not_checked_and_older_items_show_nothing(client, fake):
    d = gathered(client)  # the plain fake: an agent from before the check
    assert {(e["valueCheck"], e["sourceFields"]) for e in d["evidence"]} == {(None, None)}
    req = d["dataRequests"][0]
    client.put(f"/api/data-requests/{req['id']}", json={"answer": "Tested in March 2026."})
    answered = next(e for e in detail(client, "TR-6")["evidence"] if e["fromDataRequest"])
    assert (answered["valueCheck"], answered["sourceFields"]) == ("not_checked", None)


def test_source_fields_never_go_back_out(client, checked):
    """The estimates task gets each item's value_check, never its source record;
    nor does anything else the api sends to the agent."""
    gathered(client)
    n = len(checked.calls)
    assert start(client, "TR-6", "estimates").status_code == 202
    sent = checked.calls[n][1]
    assert {e["value_check"] for e in sent["evidence"]} == {"found", "not_checked"}
    assert all("source_fields" not in e for e in sent["evidence"])
    est = detail(client, "TR-6")["estimates"]
    for f in est["factors"]:
        if f["status"] == "estimated":
            client.post(f"/api/register/risks/TR-6/estimates/{f['factor']}/reveal", json={"analystRange": None})
            client.put(f"/api/register/risks/TR-6/estimates/{f['factor']}", json={"choice": "agent"})
    aid = client.post("/api/register/risks/TR-6/create-analysis").json()["analysisId"]
    client.post(f"/api/agent/analyses/{aid}/review")
    assert any(t == "review" for t, _ in checked.calls[n:])
    after = json.dumps([p for _, p in checked.calls[n:]])
    assert MARKER not in after and "source_fields" not in after and "sourceFields" not in after
    # The analysis document doesn't carry it either.
    assert MARKER not in json.dumps(client.get(f"/api/analyses/{aid}").json())
