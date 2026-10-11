"""Estimates, the anchoring guard and push to analysis, through the API.

The agent is faked (test_intake_pipeline.FakeAgent) and jobs run inline.
"""

import json

import pytest
from test_drafts_workflow import detail, review, scenario_for, start
from test_intake_pipeline import FakeAgent, import_register

from app import agent_client, agent_pipeline
from app.config import settings
from app.routers import agent as agent_router
from app.routers import register as register_router

ON = {"configured": True, "reason": None, "model": "claude-sonnet-5-5", "externalEnabled": True}
TEF_RANGE = {"min": 1, "ml": 4, "max": 12}  # the fake agent's tef range


@pytest.fixture
def fake(monkeypatch) -> FakeAgent:
    f = FakeAgent()
    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", f)
    for module in (register_router, agent_router):
        monkeypatch.setattr(module, "fetch_agent_status", lambda: ON)
    monkeypatch.setattr(settings, "analyst_name", "Test Analyst")
    return f


def ready(client, rid="TR-6") -> dict:
    """Import, approve the scenario, gather evidence and draft estimates."""
    import_register(client)
    s = scenario_for(client, rid)
    review(client, s["id"], "approve")
    assert start(client, rid, "evidence").status_code == 202
    assert start(client, rid, "estimates").status_code == 202
    return detail(client, rid)


def factor(d: dict, key: str) -> dict:
    return next(f for f in d["estimates"]["factors"] if f["factor"] == key)


def reveal(client, rid, key, analyst_range=None):
    return client.post(f"/api/register/risks/{rid}/estimates/{key}/reveal", json={"analystRange": analyst_range})


def decide(client, rid, key, choice, rng=None):
    body = {"choice": choice} if rng is None else {"choice": choice, "range": rng}
    return client.put(f"/api/register/risks/{rid}/estimates/{key}", json=body)


# ---------------------------------------------------------------- order and blocking

def test_estimates_need_an_approved_scenario_and_evidence(client, fake):
    import_register(client)
    assert start(client, "TR-6", "estimates").status_code == 409
    s = scenario_for(client, "TR-6")
    review(client, s["id"], "approve")
    res = start(client, "TR-6", "estimates")
    assert res.status_code == 409 and "Gather evidence first" in res.json()["detail"]
    start(client, "TR-6", "evidence")
    assert detail(client, "TR-6")["blocked"]["estimates"] is None


def test_the_agent_gets_the_current_evidence(client, fake):
    d = ready(client)
    sent = [p for t, p in fake.calls if t == "estimates"][-1]
    assert [e["id"] for e in sent["evidence"]] == [e["id"] for e in d["evidence"]]
    assert sent["scenario"]["threat_type"] and sent["data_requests"]


# ---------------------------------------------------------------- the anchoring guard

def test_agent_ranges_are_hidden_until_revealed(client, fake):
    d = ready(client)
    assert d["estimates"]["method"]["mode"] == "tef_vuln"
    tef = factor(d, "tef")
    assert (tef["status"], tef["revealed"], tef["agent"]) == ("estimated", False, None)
    # Nowhere in the risk detail: not in the estimates view, not in the drafts list.
    raw = json.dumps(d)
    assert '"rationale": "Four attempts."' not in raw and "Four attempts." not in raw
    assert all(dr["kind"] != "estimate" for dr in d["drafts"])


def test_reveal_after_entering_a_range_is_recorded(client, fake):
    ready(client)
    mine = {"min": 2, "ml": 5, "max": 15, "conf": "med"}
    d = reveal(client, "TR-6", "tef", mine).json()
    tef = factor(d, "tef")
    assert tef["revealed"] and tef["agent"]["ml"] == 4 and tef["agent"]["rationale"] == "Four attempts."
    assert tef["reveal"]["enteredBeforeReveal"] is True and tef["reveal"]["analystRange"]["ml"] == 5
    # Revealing again changes nothing.
    again = factor(reveal(client, "TR-6", "tef", None).json(), "tef")
    assert again["reveal"]["enteredBeforeReveal"] is True


def test_reveal_without_a_range_is_recorded_as_such(client, fake):
    ready(client)
    tef = factor(reveal(client, "TR-6", "vuln", None).json(), "vuln")
    assert tef["reveal"]["enteredBeforeReveal"] is False and tef["reveal"]["analystRange"] is None


def test_an_invalid_range_must_be_fixed_before_revealing(client, fake):
    ready(client)
    res = reveal(client, "TR-6", "vuln", {"min": 30, "ml": 10, "max": 20, "conf": "med"})
    assert res.status_code == 422
    assert factor(detail(client, "TR-6"), "vuln")["revealed"] is False


def test_unestimated_factors_have_nothing_to_reveal(client, fake):
    d = ready(client)
    fines = factor(d, "secondary.fines")
    assert fines["status"] == "unestimated" and fines["unestimated"]["dataRequestId"]
    req = next(r for r in d["dataRequests"] if r["id"] == fines["unestimated"]["dataRequestId"])
    assert req["team"] == "Legal" and req["factor"] == "secondary.fines"
    assert reveal(client, "TR-6", "secondary.fines").status_code == 409


# ---------------------------------------------------------------- decisions

def test_take_the_agents_range_only_after_revealing(client, fake):
    ready(client)
    res = decide(client, "TR-6", "tef", "agent")
    assert res.status_code == 409 and "Show the agent’s range" in res.json()["detail"]
    reveal(client, "TR-6", "tef")
    d = decide(client, "TR-6", "tef", "agent").json()
    dec = factor(d, "tef")["decision"]
    assert (dec["choice"], dec["ml"], dec["by"]) == ("agent", 4, "Test Analyst") and dec["evidenceIds"]


def test_keep_your_own_or_enter_a_third(client, fake):
    ready(client)
    d = decide(client, "TR-6", "primary.response", "analyst", {"min": 60000, "ml": 120000, "max": 300000, "conf": "low"}).json()
    dec = factor(d, "primary.response")["decision"]
    assert dec["choice"] == "analyst" and dec["revealedFirst"] is False and dec["ml"] == 120000
    bad = decide(client, "TR-6", "slef", "analyst", {"min": 10, "ml": 50, "max": 150, "conf": "med"})
    assert bad.status_code == 422 and "between 0 and 100" in bad.json()["detail"]
    assert decide(client, "TR-6", "slef", "analyst").status_code == 422
    # An analyst can decide a factor the agent didn't estimate.
    d = decide(client, "TR-6", "secondary.fines", "analyst", {"min": 0, "ml": 50000, "max": 500000, "conf": "low"}).json()
    assert factor(d, "secondary.fines")["decision"]["choice"] == "analyst"


def test_clearing_a_decision(client, fake):
    ready(client)
    reveal(client, "TR-6", "tef")
    decide(client, "TR-6", "tef", "agent")
    d = client.delete("/api/register/risks/TR-6/estimates/tef").json()
    assert factor(d, "tef")["decision"] is None and d["estimates"]["decided"] == 0


# ---------------------------------------------------------------- push to analysis

def test_create_analysis_from_tr6(client, fake):
    ready(client)
    reveal(client, "TR-6", "tef", {"min": 2, "ml": 5, "max": 15, "conf": "med"})
    decide(client, "TR-6", "tef", "agent")
    reveal(client, "TR-6", "vuln")
    decide(client, "TR-6", "vuln", "agent")
    decide(client, "TR-6", "primary.response", "analyst", {"min": 60000, "ml": 120000, "max": 300000, "conf": "low"})

    res = client.post("/api/register/risks/TR-6/create-analysis")
    assert res.status_code == 201, res.text
    aid = res.json()["analysisId"]
    assert sorted(res.json()["factorsPushed"]) == ["primary.response", "tef", "vuln"]

    doc = client.get(f"/api/analyses/{aid}").json()
    assert doc["title"].startswith("TR-6 ") and len(doc["states"]) == 1  # no treatment state
    assert doc["scope"]["threatType"] == "Malicious, external" and doc["scope"]["asset"].startswith("Asset for")
    assert "Firewall (affects how often the threat acts)" in doc["scope"]["controls"]
    s0 = doc["states"][0]
    assert (s0["lef"]["mode"], s0["lef"]["vulnMode"]) == ("tef_vuln", "direct")
    assert (s0["lef"]["tef"]["min"], s0["lef"]["tef"]["ml"], s0["lef"]["tef"]["max"]) == (1, 4, 12)
    assert s0["lef"]["tef"]["src"].startswith("Four attempts.\nSources: Incident History INC-2026-021")
    assert "Agent-drafted, approved by Test Analyst on " in s0["lef"]["tef"]["src"]
    assert s0["primary"]["response"]["src"].startswith("Analyst estimate by Test Analyst")
    # Undecided factors stay empty, even ones the agent estimated.
    assert s0["slef"]["min"] is None and s0["secondary"]["fines"]["min"] is None

    # The analysis runs: the pushed ranges pass the existing checks.
    run = client.post(f"/api/analyses/{aid}/runs")
    assert run.status_code == 201, run.text

    # Provenance, the link back to the risk, and the register list.
    prov = client.get(f"/api/analyses/{aid}/provenance").json()
    assert prov["linked"] and prov["riskId"] == "TR-6" and prov["mitigationPlan"]
    by = {p["factor"]: p for p in prov["factors"]}
    assert by["tef"]["origin"] == "agent" and by["tef"]["evidence"][0]["citation"] == "Incident History INC-2026-021"
    assert by["primary.response"]["origin"] == "analyst" and by["primary.response"]["evidence"] == []
    assert by["tef"]["stateId"] == s0["id"] and by["tef"]["range"]["ml"] == 4
    listed = {r["riskId"]: r for r in client.get("/api/register/risks").json()}
    assert listed["TR-6"]["analysisId"] == aid
    assert detail(client, "TR-6")["analysisId"] == aid


def test_create_analysis_needs_an_approved_scenario(client, fake):
    import_register(client)
    scenario_for(client, "TR-7")  # drafted, not approved
    res = client.post("/api/register/risks/TR-7/create-analysis")
    assert res.status_code == 409 and "Approve or edit the scenario first" in res.json()["detail"]


def test_create_analysis_without_estimates_leaves_factors_empty(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-8")
    review(client, s["id"], "approve")
    aid = client.post("/api/register/risks/TR-8/create-analysis").json()["analysisId"]
    doc = client.get(f"/api/analyses/{aid}").json()
    assert doc["states"][0]["lef"]["tef"]["min"] is None and doc["states"][0]["lef"]["mode"] == "tef_vuln"
    assert client.get(f"/api/analyses/{aid}/provenance").json()["factors"] == []


def test_provenance_for_an_ordinary_analysis(client, fake):
    aid = client.post("/api/analyses").json()["id"]
    assert client.get(f"/api/analyses/{aid}/provenance").json() == {"linked": False}



def test_tab_offers_only_the_methods_factors(client, fake):
    """The fake recommends tef_vuln with direct vulnerability: no lef, cf, poa, tcap or rs."""
    d = ready(client)
    keys = [f["factor"] for f in d["estimates"]["factors"]]
    assert keys[:2] == ["tef", "vuln"] and not {"lef", "cf", "poa", "tcap", "rs"} & set(keys)
    assert {"primary.productivity", "primary.replacement", "secondary.reputation"} <= set(keys)
    assert decide(client, "TR-6", "lef", "analyst", {"min": 1, "ml": 2, "max": 3, "conf": "med"}).status_code == 409
    # A factor the agent said nothing about can still take the analyst's range.
    res = decide(client, "TR-6", "primary.replacement", "analyst", {"min": 1000, "ml": 2000, "max": 5000, "conf": "low"})
    assert res.status_code == 200
    assert factor(res.json(), "primary.replacement")["unestimated"] is None
    assert res.json()["estimates"]["decided"] == 1
