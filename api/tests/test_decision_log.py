"""Required reasons and the decision log (UI_REBUILD.md stage 1).

The agent is faked (test_intake_pipeline.FakeAgent) and jobs run inline.
"""

import pytest
from test_drafts_workflow import detail, review, scenario_for, start
from test_estimates_api import RATIONALE, decide, factor, ready, reveal
from test_estimates_api import fake  # noqa: F401  (fixture)
from test_intake_pipeline import import_register

from app.db import SessionLocal
from app.models import DecisionLogRow

RANGE = {"min": 60000, "ml": 120000, "max": 300000, "conf": "low"}
REASON_MESSAGE = "Say why, in a sentence. It is kept with the decision record."


def log(client, rid="TR-6") -> list[dict]:
    res = client.get(f"/api/register/risks/{rid}/decision-log")
    assert res.status_code == 200
    return res.json()


# ---------------------------------------------------------------- draft reviews

def test_edit_and_reject_need_a_reason(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    edited = {**s["payload"], "condition": "No multi-factor authentication."}
    for action, payload in (("edit", edited), ("reject", None)):
        for reason in (None, "", "   too short   "):
            res = review(client, s["id"], action, payload, reason=reason)
            assert res.status_code == 422, (action, reason)
            assert res.json()["detail"] == REASON_MESSAGE
            assert res.json()["errors"][0]["path"] == "reason"
    assert detail(client, "TR-6")["scenario"]["status"] == "drafted"
    assert log(client) == []


def test_approve_needs_no_reason_but_keeps_one(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    assert review(client, s["id"], "approve").status_code == 200
    res = client.put(f"/api/drafts/{s['id']}", json={"action": "approve", "reason": "Reads right."})
    assert res.status_code == 200
    rows = log(client)
    assert [(r["step"], r["action"], r["reason"]) for r in rows] == [
        ("scenario", "approve", None), ("scenario", "approve", "Reads right.")]
    assert rows[0]["by"] == "Test Analyst" and rows[0]["subject"] == str(s["id"])


def test_edit_and_reject_are_logged_with_reason_and_fields(client, fake):
    import_register(client)
    s = scenario_for(client, "TR-6")
    edited = {**s["payload"], "condition": "No multi-factor authentication."}
    assert review(client, s["id"], "edit", edited, reason="The register says MFA is missing.").status_code == 200
    assert review(client, s["id"], "reject", reason="Wrong asset for this risk.").status_code == 200
    rows = log(client)
    assert [(r["action"], r["reason"]) for r in rows] == [
        ("edit", "The register says MFA is missing."), ("reject", "Wrong asset for this risk.")]
    assert rows[0]["detail"]["changed"] == ["condition"] and rows[0]["detail"]["kind"] == "scenario"


def test_triage_override_and_data_request_answers_are_logged(client, fake):
    import_register(client)
    client.post("/api/register/risks/TR-15/triage-override", json={"status": "qualifies", "reason": "Customer data."})
    rows = log(client, "TR-15")
    assert [(r["step"], r["action"], r["reason"]) for r in rows] == [("triage", "override", "Customer data.")]
    assert rows[0]["detail"]["from"] == "screened_out" and rows[0]["detail"]["to"] == "qualifies"

    d = ready(client)
    req = next(r for r in d["dataRequests"] if r["status"] == "open")
    client.put(f"/api/data-requests/{req['id']}", json={"answer": "Tested in March 2026."})
    answer = [r for r in log(client) if r["action"] == "answer"]
    assert len(answer) == 1 and answer[0]["step"] == "evidence" and answer[0]["detail"]["factor"] == req["factor"]


# ---------------------------------------------------------------- analyst decisions

def test_an_analyst_range_needs_a_rationale(client, fake):
    ready(client)
    for rationale in (None, "", "Seems right.   "):
        res = decide(client, "TR-6", "primary.response", "analyst", RANGE, rationale=rationale)
        assert res.status_code == 422 and res.json()["errors"][0]["path"] == "rationale"
    assert factor(detail(client, "TR-6"), "primary.response")["decision"] is None


def test_an_analyst_range_needs_evidence_or_the_placeholder_flag(client, fake):
    d = ready(client)
    res = decide(client, "TR-6", "primary.response", "analyst", RANGE, placeholder=False)
    assert res.status_code == 422
    assert res.json()["detail"] == "Tick the evidence you relied on, or mark this range as a placeholder."
    res = decide(client, "TR-6", "primary.response", "analyst", RANGE, placeholder=True)
    assert res.status_code == 200
    dec = factor(res.json(), "primary.response")["decision"]
    assert (dec["rationale"], dec["evidenceIds"], dec["placeholder"]) == (RATIONALE, [], True)

    ids = [e["id"] for e in d["evidence"][:2]]
    res = decide(client, "TR-6", "primary.response", "analyst", RANGE, placeholder=False, evidenceIds=ids)
    assert res.status_code == 200
    dec = factor(res.json(), "primary.response")["decision"]
    assert dec["evidenceIds"] == ids and dec["placeholder"] is False


def test_evidence_from_another_risk_is_refused(client, fake):
    other = ready(client, "TR-7")
    ready(client, "TR-6")
    foreign = other["evidence"][0]["id"]
    res = decide(client, "TR-6", "primary.response", "analyst", RANGE, placeholder=False, evidenceIds=[foreign])
    assert res.status_code == 422 and res.json()["errors"][0]["path"] == "evidenceIds"


def test_the_agents_range_takes_an_optional_note(client, fake):
    ready(client)
    reveal(client, "TR-6", "tef")
    assert decide(client, "TR-6", "tef", "agent").status_code == 200
    res = decide(client, "TR-6", "tef", "agent", note="Agrees with our SOC data.")
    assert factor(res.json(), "tef")["decision"]["note"] == "Agrees with our SOC data."
    assert [r["reason"] for r in log(client) if r["action"] == "decide"] == [None, "Agrees with our SOC data."]


def test_the_analysts_rationale_is_shown_but_the_agents_stays_hidden(client, fake):
    ready(client)
    decide(client, "TR-6", "tef", "analyst", {"min": 2, "ml": 5, "max": 15, "conf": "med"})
    tef = factor(detail(client, "TR-6"), "tef")
    assert tef["decision"]["rationale"] == RATIONALE and tef["agent"] is None and not tef["revealed"]


# ---------------------------------------------------------------- one row per action, never changed

def test_each_action_writes_exactly_one_row(client, fake):
    d = ready(client)
    base = len(log(client))
    steps = [
        lambda: reveal(client, "TR-6", "tef", {"min": 2, "ml": 5, "max": 15, "conf": "med"}),
        lambda: decide(client, "TR-6", "tef", "agent"),
        lambda: decide(client, "TR-6", "vuln", "analyst", {"min": 2, "ml": 10, "max": 30, "conf": "med"},
                       placeholder=False, evidenceIds=[d["evidence"][0]["id"]]),
        lambda: client.delete("/api/register/risks/TR-6/estimates/tef"),
        lambda: client.put(f"/api/data-requests/{d['dataRequests'][0]['id']}", json={"answer": "From Legal."}),
        lambda: client.post("/api/register/risks/TR-6/create-analysis", json={"acknowledgeStale": True}),
    ]
    expected = ["reveal", "decide", "decide", "clear", "answer", "create_analysis"]
    for n, (step, action) in enumerate(zip(steps, expected), start=1):
        assert step().status_code in (200, 201)
        rows = log(client)
        assert len(rows) == base + n and rows[-1]["action"] == action, action
    rows = log(client)
    reveal_row, vuln = rows[base], rows[base + 2]
    assert reveal_row["detail"]["enteredFirst"] is True and reveal_row["subject"] == "tef"
    assert vuln["detail"]["range"] == {"min": 2, "ml": 10, "max": 30, "conf": "med"}
    assert vuln["detail"]["evidenceIds"] == [d["evidence"][0]["id"]] and vuln["detail"]["placeholder"] is False
    assert vuln["detail"]["sawAgentRange"] is False and vuln["reason"] == RATIONALE
    created = rows[-1]["detail"]
    assert created["acknowledgedStale"] is True and created["factorsPushed"] == ["vuln"]
    # Revealing again or clearing an undecided factor records nothing.
    reveal(client, "TR-6", "tef")
    client.delete("/api/register/risks/TR-6/estimates/slef")
    assert len(log(client)) == len(rows)
    # Oldest first.
    assert [r["at"] for r in rows] == sorted(r["at"] for r in rows)


def test_rows_are_never_changed_or_deleted(client, fake):
    d = ready(client)
    s = d["scenario"]
    review(client, s["id"], "edit", {**s["payload"], "condition": "Changed."}, reason="Register says so.")
    decide(client, "TR-6", "slef", "analyst", {"min": 10, "ml": 30, "max": 60, "conf": "med"})
    before = log(client)
    # Reversing every decision adds rows; the earlier ones stay as they were.
    review(client, s["id"], "approve")
    client.delete("/api/register/risks/TR-6/estimates/slef")
    after = log(client)
    assert after[:len(before)] == before and len(after) == len(before) + 2

    with SessionLocal() as session:
        row = session.get(DecisionLogRow, before[0]["id"])
        row.reason = "rewritten"
        with pytest.raises(RuntimeError, match="append-only"):
            session.commit()
        session.rollback()
        session.delete(session.get(DecisionLogRow, before[0]["id"]))
        with pytest.raises(RuntimeError, match="append-only"):
            session.commit()
    assert log(client) == after


def test_a_risk_without_rows_returns_an_empty_log(client, fake):
    import_register(client)
    assert log(client, "TR-8") == []
    assert client.get("/api/register/risks/NOPE/decision-log").status_code == 404


# ---------------------------------------------------------------- push to analysis

def test_the_pushed_src_has_four_parts_in_order(client, fake):
    d = ready(client)
    ev = d["evidence"][:2]
    decide(client, "TR-6", "primary.response", "analyst", RANGE, placeholder=True, evidenceIds=[e["id"] for e in ev])
    decide(client, "TR-6", "slef", "analyst", {"min": 10, "ml": 30, "max": 60, "conf": "med"}, placeholder=False,
           evidenceIds=[ev[0]["id"]])
    aid = client.post("/api/register/risks/TR-6/create-analysis").json()["analysisId"]
    doc = client.get(f"/api/analyses/{aid}").json()
    s0 = doc["states"][0]
    lines = s0["primary"]["response"]["src"].split("\n")
    assert lines[0] == RATIONALE
    assert lines[1] == "Sources: " + "; ".join(e["citation"] for e in ev)
    assert lines[2] == "Placeholder until better data is available."
    assert lines[3].startswith("Analyst estimate by Test Analyst on ") and len(lines) == 4
    assert "Placeholder" not in s0["slef"]["src"]

    prov = {p["factor"]: p for p in client.get(f"/api/analyses/{aid}/provenance").json()["factors"]}
    assert prov["primary.response"]["placeholder"] is True and prov["primary.response"]["range"]["placeholder"] is True
    assert prov["slef"]["placeholder"] is False
    assert [e["id"] for e in prov["primary.response"]["evidence"]] == [e["id"] for e in ev]


def test_the_input_review_still_strips_the_approval_line(client, fake):
    from app.analysis_agent import APPROVAL_LINE

    src = f"{RATIONALE}\nSources: X\nPlaceholder until better data is available.\nAnalyst estimate by A on 2026-10-12."
    assert APPROVAL_LINE.sub("", src).strip().endswith("Placeholder until better data is available.")
