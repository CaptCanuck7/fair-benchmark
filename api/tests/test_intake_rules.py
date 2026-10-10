"""The deterministic halves of the quality check and triage (no model)."""

import pytest
from conftest import AGENT_DATA

from app.register.parser import parse_workbook
from app.register.quality import Gap, blocking_gaps, combine, rule_gaps
from app.register.triage import triage, would_qualify

GOOD_JUDGEMENT = {"names_asset": True, "names_condition": True, "names_loss_path": True, "gaps": [], "questions": []}


@pytest.fixture(scope="module")
def register():
    parsed = parse_workbook((AGENT_DATA / "tactical_risk_register_test.xlsx").read_bytes())
    return {r.risk_id: r for r in parsed.risks}


def gaps_of(risk) -> list[Gap]:
    return rule_gaps(risk.fields, risk.sections, risk.structured)


def fields_of(gaps) -> set[str]:
    return {g.field for g in gaps}


# ---------------------------------------------------------------- quality rules

def test_well_formed_entries_have_no_rule_gaps(register):
    for rid in ("TR-6", "TR-7", "TR-8", "TR-9", "TR-10", "TR-11", "TR-12", "TR-13", "TR-14", "TR-15"):
        assert gaps_of(register[rid]) == [], rid


def test_tr17_gaps_name_assets_environment_owner_and_vague_analysis(register):
    gaps = gaps_of(register["TR-17"])
    assert fields_of(gaps) == {"assets", "environment", "risk_owner", "risk_statement", "risk_analysis"}
    assert any("only 100 characters" in g.problem for g in gaps)
    assert any("section labels" in g.problem for g in gaps)


def test_tr18_gaps_name_likelihood_action_assets_and_vague_analysis(register):
    gaps = gaps_of(register["TR-18"])
    assert fields_of(gaps) == {"assets", "baseline_likelihood", "risk_action", "risk_statement", "risk_analysis"}


def test_tr16_lists_missing_assets_and_environment(register):
    assert fields_of(gaps_of(register["TR-16"])) == {"assets", "environment"}


def test_invalid_score_is_reported_differently_from_a_missing_one():
    fields = {"asset_ids": ["A-1"], "environment": "E", "risk_owner": "O", "risk_action": "Mitigate",
              "baseline_impact": 7, "baseline_likelihood": None}
    gaps = {g.field: g.problem for g in rule_gaps(fields, {"risk_statement": "x" * 250}, True)}
    assert gaps["baseline_impact"] == "The baseline impact isn’t a whole number from 1 to 5."
    assert gaps["baseline_likelihood"] == "No baseline likelihood score."


def test_structured_text_without_a_risk_statement_is_a_gap():
    fields = {"asset_ids": ["A-1"], "environment": "E", "risk_owner": "O", "risk_action": "Mitigate",
              "baseline_impact": 3, "baseline_likelihood": 3}
    gaps = rule_gaps(fields, {"detailed_analysis": "x" * 250}, True)
    assert [(g.field, g.problem) for g in gaps] == [("risk_statement", "The analysis has no Risk Statement section.")]


# ---------------------------------------------------------------- blocking

def test_impact_likelihood_and_statement_always_block():
    gaps = [Gap("baseline_impact", "p"), Gap("baseline_likelihood", "p"), Gap("risk_statement", "p"),
            Gap("risk_owner", "p"), Gap("risk_action", "p"), Gap("risk_analysis", "p")]
    assert fields_of(blocking_gaps(gaps, would_qualify=False)) == {"baseline_impact", "baseline_likelihood",
                                                                  "risk_statement"}


def test_assets_and_environment_block_only_qualifying_risks():
    gaps = [Gap("assets", "p"), Gap("environment", "p")]
    assert blocking_gaps(gaps, would_qualify=False) == []
    assert fields_of(blocking_gaps(gaps, would_qualify=True)) == {"assets", "environment"}


def test_rule_gaps_override_a_positive_model_view(register):
    r = register["TR-17"]  # score 9: qualifies, so assets and environment block too
    q = combine(gaps_of(r), would_qualify(r.baseline_score, r.fields["baseline_impact"], 6), GOOD_JUDGEMENT)
    assert q["status"] == "needs_info"
    assert set(q["blockedBy"]) == {"assets", "environment", "risk_statement"}


def test_tr16_is_ready_with_its_gaps_listed(register):
    r = register["TR-16"]
    q = combine(gaps_of(r), would_qualify(r.baseline_score, r.fields["baseline_impact"], 6), GOOD_JUDGEMENT)
    assert q["status"] == "ready"
    assert {g["field"] for g in q["gaps"]} == {"assets", "environment"}
    assert not any(g["blocking"] for g in q["gaps"])


@pytest.mark.parametrize("flag", ["names_condition", "names_loss_path"])
def test_model_judgement_can_make_an_entry_needs_info(flag):
    q = combine([], True, {**GOOD_JUDGEMENT, flag: False})
    assert q["status"] == "needs_info"


@pytest.mark.parametrize("flag", ["names_asset", "names_condition", "names_loss_path"])
def test_model_checks_follow_the_qualifying_threshold(flag):
    judgement = {**GOOD_JUDGEMENT, flag: False}
    blocked = combine([], True, judgement)
    assert blocked["status"] == "needs_info" and len(blocked["blockedBy"]) == 1
    listed = combine([], False, judgement)
    assert listed["status"] == "ready" and listed["blockedBy"] == [] and len(listed["unmetChecks"]) == 1


def test_model_gaps_are_added_once_and_never_block():
    judgement = {**GOOD_JUDGEMENT, "gaps": [{"field": "baseline_controls", "problem": "Controls are vague."},
                                            {"field": "assets", "problem": "No assets are listed."}],
                 "questions": ["Which controls cover the SFTP servers?"]}
    q = combine([Gap("assets", "No assets are listed.")], False, judgement)
    assert [(g["field"], g["source"], g["blocking"]) for g in q["gaps"]] == [
        ("assets", "rule", False), ("baseline_controls", "agent", False)]
    assert q["questions"] == ["Which controls cover the SFTP servers?"]


# ---------------------------------------------------------------- triage rule

@pytest.mark.parametrize("score,impact,threshold,expected", [
    (6, 3, 6, "qualifies"),        # exactly at the threshold
    (5, 1, 6, "screened_out"),     # one below it (impact 1 x likelihood 5)
    (5, 5, 6, "qualifies"),        # impact 5 x likelihood 1: below the threshold, but impact 5
    (4, 2, 6, "screened_out"),     # TR-16
    (2, 1, 6, "screened_out"),     # TR-15
    (12, 4, 12, "qualifies"),      # a higher threshold
    (10, 5, 12, "qualifies"),      # impact 5 still qualifies
    (None, 4, 6, "screened_out"),  # no score
])
def test_triage_threshold_boundary_and_impact_5(score, impact, threshold, expected):
    assert triage(score, impact, threshold)["status"] == expected


def test_triage_records_the_rule_used():
    assert triage(6, 3, 6)["rule"] == "Baseline score 6 is at or above the threshold of 6."
    assert triage(5, 5, 6)["rule"].startswith("Baseline impact is 5")
    assert triage(5, 1, 6)["rule"] == "Baseline score 5 is below the threshold of 6."
    assert triage(None, 4, 6)["rule"] == "There is no baseline score to compare with the threshold."


def test_section_14_triage_scores(register):
    expected = {"TR-6": 12, "TR-7": 15, "TR-8": 12, "TR-9": 12, "TR-10": 8, "TR-11": 8, "TR-12": 8, "TR-13": 12,
                "TR-14": 6, "TR-15": 2, "TR-16": 4}
    for rid, score in expected.items():
        r = register[rid]
        t = triage(r.baseline_score, r.fields["baseline_impact"], 6)
        assert t["score"] == score, rid
        assert t["status"] == ("qualifies" if score >= 6 else "screened_out"), rid
