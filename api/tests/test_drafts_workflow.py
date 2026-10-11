"""Scenario and vectors drafting, and the approve / edit / reject workflow.

The agent is faked (see test_intake_pipeline.FakeAgent) and jobs run inline.
"""

import pytest
from test_intake_pipeline import FakeAgent, import_register  # noqa: F401  (fixture below)

from app import agent_client, agent_pipeline
from app.config import settings
from app.routers import agent as agent_router
from app.routers import register as register_router

ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}


@pytest.fixture
def fake(monkeypatch) -> FakeAgent:
    f = FakeAgent()
    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", f)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    monkeypatch.setattr(settings, "analyst_name", "Test Analyst")
    return f


def detail(client, rid: str) -> dict:
    return client.get(f"/api/register/risks/{rid}").json()


def start(client, rid: str, task: str):
    return client.post(f"/api/agent/risks/{rid}/{task}")


def review(client, draft_id: int, action: str, payload=None):
    body = {"action": action} if payload is None else {"action": action, "payload": payload}
    return client.put(f"/api/drafts/{draft_id}", json=body)


def scenario_for(client, rid: str) -> dict:
    assert start(client, rid, "scenario").status_code == 202
    return detail(client, rid)["scenario"]


# ---------------------------------------------------------------- who gets a scenario

def test_only_ready_qualifying_risks_get_a_scenario(client, fake):
    import_register(client)
    for rid, why in (("TR-15", "Only risks that qualify"), ("TR-16", "Only risks that qualify"),
                     ("TR-17", "quality check must find this entry ready"),
                     ("TR-18", "quality check must find this entry ready")):
        res = start(client, rid, "scenario")
        assert res.status_code == 409 and why in res.json()["detail"], rid
        assert detail(client, rid)["scenario"] is None
    assert detail(client, "TR-15")["blocked"]["scenario"].startswith("Only risks that qualify")
    assert detail(client, "TR-6")["blocked"] == {"scenario": None,
                                                 "vectors": "Draft and approve the scenario first.",
                                                 "evidence": "Draft and approve the scenario first."}


def test_scenario_draft_is_recorded_and_labeled(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    assert s["kind"] == "scenario" and s["status"] == "drafted" and s["reviewer"] is None
    assert s["promptVersion"] == "scenario.v1" and s["model"] == "claude-sonnet-5-5"
    # The approved classification is passed along as a hint.
    sent = [p for t, p in fake.calls if t == "scenario"][-1]
    assert sent["classification"] == {"primary_type": "missing_control", "secondary_type": None}
    assert [r["task"] for r in detail(client, "TR-6")["runs"]][0] == "scenario"


def test_an_overridden_risk_can_get_a_scenario(client, fake):
    import_register(client)
    client.post("/api/register/risks/TR-15/triage-override", json={"status": "qualifies", "reason": "Customer data."})
    assert start(client, "TR-15", "scenario").status_code == 202


# ---------------------------------------------------------------- approval gates

def test_vectors_wait_for_an_approved_scenario(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    res = start(client, "TR-6", "vectors")
    assert res.status_code == 409 and "Approve or edit the scenario first" in res.json()["detail"]

    after = review(client, s["id"], "approve").json()
    assert after["scenario"]["status"] == "approved" and after["scenario"]["reviewer"] == "Test Analyst"
    assert after["scenario"]["reviewedAt"] and after["blocked"]["vectors"] is None

    assert start(client, "TR-6", "vectors").status_code == 202
    v = detail(client, "TR-6")["vectors"]
    assert v["effective"]["kind"] == "attack_vectors"
    assert v["effective"]["paths"][0]["origin"] == "from_register"  # TR-6 has exploit paths
    assert v["payload"]["basedOn"]["scenarioDraftId"] == s["id"]
    assert detail(client, "TR-6")["vectorsStale"] is False


def test_failure_scenarios_get_failure_paths(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-12")  # backup restoration: the fake drafts a failure scenario
    review(client, s["id"], "approve")
    start(client, "TR-12", "vectors")
    v = detail(client, "TR-12")["vectors"]["effective"]
    assert v["kind"] == "failure_paths" and v["paths"][0]["what_fails"]
    assert v["paths"][0]["origin"] == "agent_drafted"  # TR-12 has no exploit paths


def test_vectors_are_built_from_the_analysts_edit(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-8")
    edited = {**{k: v for k, v in s["payload"].items()}, "asset": "Production cloud account (edited)"}
    res = review(client, s["id"], "edit", edited)
    assert res.status_code == 200
    sc = res.json()["scenario"]
    assert sc["status"] == "edited" and sc["effective"]["asset"] == "Production cloud account (edited)"
    assert sc["payload"]["asset"] == s["payload"]["asset"]  # the agent's version is kept
    start(client, "TR-8", "vectors")
    sent = [p for t, p in fake.calls if t == "vectors"][-1]
    assert sent["scenario"]["asset"] == "Production cloud account (edited)"


def test_changing_the_scenario_marks_vectors_out_of_date(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-7")
    review(client, s["id"], "approve")
    start(client, "TR-7", "vectors")
    assert detail(client, "TR-7")["vectorsStale"] is False
    review(client, s["id"], "edit", {**s["payload"], "condition": "No multi-factor authentication at all."})
    assert detail(client, "TR-7")["vectorsStale"] is True


def test_rejecting_the_scenario_blocks_vectors_but_keeps_the_draft(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-9")
    res = review(client, s["id"], "reject").json()
    assert res["scenario"]["status"] == "rejected"
    assert res["blocked"]["vectors"].startswith("Approve or edit the scenario first")
    assert start(client, "TR-9", "vectors").status_code == 409
    # A later review can reverse a rejection.
    assert review(client, s["id"], "approve").json()["scenario"]["status"] == "approved"


def test_approving_an_edited_draft_keeps_the_edit(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-11")
    review(client, s["id"], "edit", {**s["payload"], "notes": ["Check record counts."]})
    again = review(client, s["id"], "approve").json()["scenario"]
    assert again["status"] == "edited" and again["effective"]["notes"] == ["Check record counts."]


# ---------------------------------------------------------------- edit validation

def test_an_invalid_scenario_edit_is_rejected_with_paths(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-13")
    bad = {**s["payload"], "effect": "Privacy", "controls": [{"control": "", "factor": "luck", "helps": True}]}
    res = review(client, s["id"], "edit", bad)
    assert res.status_code == 422
    paths = {e["path"] for e in res.json()["errors"]}
    assert {"payload.effect", "payload.controls.0.control", "payload.controls.0.factor"} <= paths
    assert detail(client, "TR-13")["scenario"]["status"] == "drafted"


def test_unknown_fields_in_an_edit_are_refused(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-13")
    assert review(client, s["id"], "edit", {**s["payload"], "status": "approved"}).status_code == 422


def test_failure_path_edits_must_say_what_fails(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-12")
    review(client, s["id"], "approve")
    start(client, "TR-12", "vectors")
    v = detail(client, "TR-12")["vectors"]
    bad = {**v["payload"], "paths": [{**v["payload"]["paths"][0], "what_fails": ""}]}
    res = review(client, v["id"], "edit", bad)
    assert res.status_code == 422 and "Say what fails" in res.json()["errors"][0]["message"]
    ok = review(client, v["id"], "edit", {**v["payload"], "paths": [{**v["payload"]["paths"][0], "origin": "analyst"}]})
    assert ok.status_code == 200
    assert ok.json()["vectors"]["editedPayload"]["basedOn"] == v["payload"]["basedOn"]  # kept through the edit


def test_an_edit_needs_a_payload(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    assert review(client, s["id"], "edit").status_code == 422


# ---------------------------------------------------------------- the other draft kinds

def test_quality_and_triage_reviews(client, fake):
    import_register(client)
    d = detail(client, "TR-6")
    q, t = d["intake"]["quality"], d["intake"]["triage"]
    assert review(client, q["id"], "approve").json()["intake"]["quality"]["status"] == "approved"
    assert review(client, q["id"], "edit", q["payload"]).status_code == 409
    for action in ("edit", "reject"):
        res = review(client, t["id"], action, t["payload"] if action == "edit" else None)
        assert res.status_code == 409 and "triage override" in res.json()["detail"]
    assert review(client, t["id"], "approve").json()["intake"]["triage"]["status"] == "approved"


def test_an_edited_classification_is_passed_to_the_scenario(client, fake):
    import_register(client)
    c = detail(client, "TR-10")["intake"]["classification"]
    edit = {"primary_type": "third_party", "secondary_type": "unsupported_software", "confidence": "high",
            "reason": "The weakness sits with the benefits provider's legacy API."}
    res = review(client, c["id"], "edit", edit)
    assert res.status_code == 200
    r = {x["riskId"]: x for x in client.get("/api/register/risks").json()}["TR-10"]
    assert (r["classification"], r["secondaryClassification"]) == ("third_party", "unsupported_software")
    scenario_for(client, "TR-10")
    sent = [p for t, p in fake.calls if t == "scenario"][-1]
    assert sent["classification"]["primary_type"] == "third_party"

    same = {**edit, "secondary_type": "third_party"}
    assert review(client, c["id"], "edit", same).status_code == 422


def test_a_rejected_classification_is_not_used(client, fake):
    import_register(client)
    c = detail(client, "TR-9")["intake"]["classification"]
    review(client, c["id"], "reject")
    r = {x["riskId"]: x for x in client.get("/api/register/risks").json()}["TR-9"]
    assert r["classification"] is None
    assert detail(client, "TR-9")["intake"]["classification"]["status"] == "rejected"  # still shown
    scenario_for(client, "TR-9")
    assert [p for t, p in fake.calls if t == "scenario"][-1]["classification"] is None


def test_missing_draft_is_404(client, fake):
    assert review(client, 99999, "approve").status_code == 404
