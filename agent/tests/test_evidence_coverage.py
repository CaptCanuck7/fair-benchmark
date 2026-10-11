"""Required lookups and source coverage for evidence gathering (AGENT_FIXES.md fix 7)."""

import pytest
from test_evidence import ALL_GROUPS, REQUESTS, llm, outbound, tool_call, toolbox
from test_llm import FakeClient, reply
from test_scenario_vectors import FAILURE_SCENARIO, SCENARIO
from test_tasks import RISK

from app.schemas import EvidenceRequest
from app.tasks import evidence

ANSWER = {"items": ALL_GROUPS, "data_requests": REQUESTS}


def request(primary="missing_control", secondary=None, scenario=SCENARIO) -> EvidenceRequest:
    return EvidenceRequest(risk=RISK, scenario=scenario,
                           classification={"primary_type": primary, "secondary_type": secondary})


def tools(out) -> dict:
    return out.notes["coverage"]["tools"]


# ---------------------------------------------------------------- which lookups are required


def test_third_party_malicious_requires_all_three():
    box = toolbox(external=True, cve_allowed=True)
    assert set(evidence.required_tools(request("third_party"), box)) == {"library_lookup", "nvd_search", "web_search"}
    assert set(evidence.required_tools(request("missing_control", "unsupported_software"), box)) == \
        {"library_lookup", "nvd_search", "web_search"}
    assert set(evidence.required_tools(request("missing_control"), box)) == {"library_lookup", "nvd_search"}


def test_a_non_malicious_threat_requires_only_the_library():
    box = toolbox(external=True, cve_allowed=False)  # as main.make_toolbox builds it for a failure scenario
    assert set(evidence.required_tools(request("third_party", scenario=FAILURE_SCENARIO), box)) == {"library_lookup"}


def test_external_sources_off_means_only_the_library_is_required_and_the_rest_not_offered():
    box = toolbox(external=False)
    assert set(evidence.required_tools(request("third_party"), box)) == {"library_lookup"}
    fake = FakeClient(tool_call("library_lookup", {"query": "breach frequency"}), reply(ANSWER))
    out = evidence.run(llm(fake), request("third_party"), box).output
    t = tools(out)
    for name in ("nvd_search", "web_search", "attack_techniques", "kev_check"):
        assert t[name]["offered"] is False and t[name]["required"] is False and t[name]["reason"] == "external_off"
    assert t["library_lookup"]["checks"] == 1


# ---------------------------------------------------------------- the loop enforces them


def test_an_answer_without_a_required_lookup_gets_one_reminder_then_the_lookup():
    box = toolbox(external=False)
    fake = FakeClient(tool_call("internal_records", {"sheets": ["incidents", "assets"]}), reply(ANSWER),
                      tool_call("library_lookup", {"query": "breach frequency"}, "tu2"), reply(ANSWER))
    result = evidence.run(llm(fake), request(), box)
    reminder = fake.calls[2]["messages"][-1]["content"]
    assert "library_lookup" in reminder and "required" in reminder
    t = tools(result.output)
    assert t["library_lookup"] == {**t["library_lookup"], "calls": 1, "checks": 1, "reason": None}
    assert t["internal_records"]["checks"] == 1 and t["internal_records"]["items"] == 2
    assert result.attempts == 1  # the reminder isn't a validation retry


def test_a_lookup_still_missing_after_the_reminder_is_reported_not_checked():
    box = toolbox(external=False)
    fake = FakeClient(tool_call("internal_records", {"sheets": ["incidents", "assets"]}), reply(ANSWER),
                      reply(ANSWER))
    out = evidence.run(llm(fake), request(), box).output
    assert len(fake.calls) == 3  # one reminder, no more
    lib = tools(out)["library_lookup"]
    assert (lib["required"], lib["calls"], lib["checks"], lib["reason"]) == (True, 0, 0, "not_called")
    assert out.items  # the answer is still accepted


def test_a_blocked_required_lookup_is_an_attempt_not_a_check():
    out_client, log = outbound({}, identifiers=[("asset_id", "Asset-412")])
    box = toolbox(external=True, cve_allowed=True, out=out_client)
    fake = FakeClient(tool_call("library_lookup", {"query": "breach frequency"}),
                      tool_call("nvd_search", {"keyword": "Asset-412 sftp"}, "tu2"), reply(ANSWER))
    out = evidence.run(llm(fake), request(), box).output
    assert len(fake.calls) == 3  # no reminder: the blocked call counts as an attempt
    nvd = tools(out)["nvd_search"]
    assert (nvd["calls"], nvd["blocked"], nvd["checks"], nvd["reason"]) == (1, 1, 0, "blocked")
    assert [e.blocked_reason for e in log] == ["identifier:asset_id"]


def test_coverage_names_the_budget_and_the_threat_type():
    box = toolbox(external=True, cve_allowed=False)
    cov = evidence.coverage(box, {"library_lookup": "why"}, [], budget_spent=True)
    assert cov["budgetSpent"] is True
    assert cov["tools"]["library_lookup"]["reason"] == "budget"
    assert cov["tools"]["nvd_search"]["reason"] == "threat_type"
    assert cov["tools"]["web_search"]["offered"] is True and cov["tools"]["web_search"]["reason"] == "budget"
    cov = evidence.coverage(box, {}, [], budget_spent=False)
    assert cov["tools"]["web_search"]["reason"] is None  # offered, not required, not called: no reason


def test_the_prompt_is_v2_and_lists_the_required_lookups():
    from app.tasks.common import load_prompt
    assert evidence.PROMPT_VERSION == "evidence.v2"
    assert "Required lookups" in load_prompt("evidence.v2") and "Required lookups" not in load_prompt("evidence.v1")
    user = evidence.build_user(request("third_party"), toolbox(), {"library_lookup": "always"})
    assert "Required lookups for this run" in user and "- library_lookup: always" in user


@pytest.mark.parametrize("name", evidence.EVIDENCE_TOOLS)
def test_every_evidence_tool_is_in_the_coverage(name):
    cov = evidence.coverage(toolbox(), {}, [], budget_spent=False)
    assert name in cov["tools"]
