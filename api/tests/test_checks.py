import pytest

from app.engine.checks import compare_checks, post_checks, pre_checks
from app.engine.simulate import run_analysis, simulate_state, summarize
from app.schemas import Analysis, Dist, State
from conftest import dist, simple_state


def codes(checks: list[dict]) -> set[str]:
    return {c["code"] for c in checks}


def post(state: State, controls: str = "", n: int = 10_000) -> list[dict]:
    r = summarize(simulate_state(state, n, 20260930), None)
    return post_checks(state, r, controls)


def fake_result(**kw) -> dict:
    r = {"lefMean": 0.3, "meanAnnualLoss": 100_000, "p50": 50_000, "p95": 200_000,
         "chanceAnyLoss": 0.3, "derivedVulnerability": None, "secondaryShareOfLoss": 0.0, "events": 3000}
    r.update(kw)
    return r


# ---------------------------------------------------------------- pre-run

def test_blank_state_needs_tef_vuln_and_primary():
    out = pre_checks(State(), 0)
    assert all(c["level"] == "error" for c in out)
    by_path = {c["path"]: c for c in out}
    assert by_path["states[0].lef.tef"]["message"] == "Threat event frequency: Enter a range for threat event frequency."
    assert by_path["states[0].lef.tef"]["code"] == "missing_factor"
    assert "states[0].lef.vuln" in by_path
    assert by_path["states[0].primary.response"]["code"] == "no_primary"


@pytest.mark.parametrize("mode,vuln_mode,required", [
    ("lef", "direct", {"lef"}),
    ("lef", "tcap_rs", {"lef"}),
    ("tef_vuln", "direct", {"tef", "vuln"}),
    ("tef_vuln", "tcap_rs", {"tef", "tcap", "rs"}),
    ("cf_poa", "direct", {"cf", "poa", "vuln"}),
    ("cf_poa", "tcap_rs", {"cf", "poa", "tcap", "rs"}),
])
def test_required_factors_by_method(mode, vuln_mode, required):
    s = State()
    s.lef.mode, s.lef.vuln_mode = mode, vuln_mode
    s.primary.response = dist(1, 2, 3)
    missing = {c["path"].split(".")[-1] for c in pre_checks(s, 2) if c["code"] == "missing_factor"}
    assert missing == required
    assert all(c["path"].startswith("states[2].") for c in pre_checks(s, 2))


def test_invalid_required_factor_uses_validation_message():
    s = simple_state()
    s.lef.lef = Dist(min=5, ml=1, max=10)
    out = pre_checks(s, 1)
    assert out == [{
        "level": "error", "code": "invalid_factor", "title": "Loss event frequency",
        "detail": "Keep minimum ≤ most likely ≤ maximum.",
        "message": "Loss event frequency: Keep minimum ≤ most likely ≤ maximum.",
        "path": "states[1].lef.lef",
    }]


def test_invalid_optional_factors():
    s = simple_state()
    s.primary.productivity = Dist(min=1, ml=None, max=3)
    s.secondary.fines = Dist(min=-1, ml=2, max=3)
    s.slef = Dist(min=10, ml=50, max=120)
    out = {c["path"]: c["message"] for c in pre_checks(s, 0)}
    assert out["states[0].primary.productivity"] == "Primary productivity: Enter all three values: minimum, most likely and maximum."
    assert out["states[0].secondary.fines"] == "Secondary fines and judgments: Values can’t be negative."
    assert out["states[0].slef"] == "Secondary loss event frequency: Use values between 0 and 100."


def test_unused_frequency_factors_are_ignored():
    s = simple_state()
    s.lef.tef = Dist(min=5, ml=1, max=10)  # invalid, but mode is lef
    assert pre_checks(s) == []


def test_secondary_without_slef_is_error():
    s = simple_state()
    s.secondary.response = dist(1, 2, 3)
    out = pre_checks(s)
    assert codes(out) == {"secondary_without_slef"}
    assert out[0]["level"] == "error" and out[0]["path"] == "states[0].slef"


def test_slef_without_secondary_is_warning():
    s = simple_state()
    s.slef = dist(10, 20, 30)
    out = pre_checks(s)
    assert codes(out) == {"slef_without_secondary"} and out[0]["level"] == "warn"


def test_valid_state_has_no_pre_checks(product_x):
    assert pre_checks(product_x.states[0]) == []


# ---------------------------------------------------------------- post-run

def test_reference_case_post_checks(product_x):
    r = run_analysis(product_x)["states"][0]
    got = codes(r["checks"])
    # These describe the reference case and should fire.
    assert {"median_zero", "heavy_tail", "secondary_driven"} <= got
    # These should not.
    assert got.isdisjoint({"lef_high", "lef_rare", "controls_vs_vuln", "derived_vuln", "wide_ranges",
                           "no_uncertainty", "undocumented", "few_events", "ok"})


def test_lef_high():
    s = simple_state()
    s.lef.lef = dist(2, 3, 5)
    out = [c for c in post(s) if c["code"] == "lef_high"]
    assert out and out[0]["level"] == "warn"
    assert out[0]["message"].startswith("Frequency looks high: the model expects about 3.")


def test_lef_rare():
    s = simple_state()
    s.lef.lef = dist(0.001, 0.005, 0.01)
    out = [c for c in post(s) if c["code"] == "lef_rare"]
    assert out and out[0]["level"] == "info" and "about once every" in out[0]["message"]


def test_controls_vs_vulnerability():
    s = simple_state()
    s.lef.mode = "tef_vuln"
    s.lef.tef = dist(0.1, 0.5, 1)
    s.lef.vuln = dist(30, 60, 90)
    assert "controls_vs_vuln" in codes(post(s, controls="MFA"))
    assert "controls_vs_vuln" not in codes(post(s, controls="   "))
    s.lef.vuln = dist(10, 40, 90)
    assert "controls_vs_vuln" not in codes(post(s, controls="MFA"))


def test_derived_vulnerability_info():
    s = simple_state()
    s.lef.mode, s.lef.vuln_mode = "tef_vuln", "tcap_rs"
    s.lef.tef = dist(0.5, 1, 2)
    s.lef.tcap, s.lef.rs = dist(40, 60, 80), dist(50, 70, 90)
    out = [c for c in post(s) if c["code"] == "derived_vuln"]
    assert out and "of comparisons" in out[0]["message"]


def test_median_zero():
    assert "median_zero" in codes(post_checks(simple_state(), fake_result(p50=0)))
    assert "median_zero" not in codes(post_checks(simple_state(), fake_result(p50=0, meanAnnualLoss=0)))


def test_heavy_tail():
    assert "heavy_tail" in codes(post_checks(simple_state(), fake_result(p95=600_000)))
    assert "heavy_tail" not in codes(post_checks(simple_state(), fake_result(p95=500_000)))


def test_secondary_driven():
    assert "secondary_driven" in codes(post_checks(simple_state(), fake_result(secondaryShareOfLoss=0.71)))
    assert "secondary_driven" not in codes(post_checks(simple_state(), fake_result(secondaryShareOfLoss=0.7)))


def test_wide_ranges_deduped():
    s = simple_state()
    s.primary.response = dist(1_000, 10_000, 200_000)
    s.slef = dist(10, 20, 30)
    s.secondary.response = dist(1_000, 10_000, 200_000)
    s.secondary.fines = dist(0, 10_000, 200_000)  # min 0: not counted
    out = [c for c in post_checks(s, fake_result()) if c["code"] == "wide_ranges"]
    assert out[0]["message"] == ("Very wide ranges: Response. Fine if the uncertainty is real; "
                                 "narrowing them with data would sharpen the result.")


def test_no_uncertainty():
    s = simple_state()
    s.lef.lef = dist(0.3, 0.3, 0.3)
    out = [c for c in post_checks(s, fake_result()) if c["code"] == "no_uncertainty"]
    assert out[0]["level"] == "warn" and "Loss event frequency has the same" in out[0]["message"]
    s.primary.response = dist(5, 5, 5)
    out = [c for c in post_checks(s, fake_result()) if c["code"] == "no_uncertainty"]
    assert "Loss event frequency, Response have the same" in out[0]["message"]


def test_undocumented_count():
    s = simple_state()
    s.primary.response = dist(1, 2, 3, src="")
    s.primary.replacement = dist(1, 2, 3, src="  ")
    out = [c for c in post_checks(s, fake_result()) if c["code"] == "undocumented"]
    assert out[0]["message"].startswith("Undocumented estimates: 2 of 3 factors")


def test_few_events():
    assert "few_events" in codes(post_checks(simple_state(), fake_result(events=49)))
    assert "few_events" not in codes(post_checks(simple_state(), fake_result(events=50)))


def test_ok_when_nothing_fires():
    out = post_checks(simple_state(), fake_result())
    assert [c["code"] for c in out] == ["ok"]
    assert out[0]["level"] == "ok" and out[0]["message"].startswith("No problems found. The inputs pass")


# ---------------------------------------------------------------- compare

def _states(*costs):
    out = [simple_state(name="Current state")]
    for i, c in enumerate(costs, 1):
        out.append(simple_state(name=f"Option {i}", cost=c))
    return out


def test_compare_treatment_worse():
    out = compare_checks(_states(1_000), [{"meanAnnualLoss": 100}, {"meanAnnualLoss": 120}])
    assert "treatment_worse" in codes(out)
    assert out[0]["message"].startswith("Option 1 shows more loss than the current state.")
    assert out[0]["path"] == "states[1]"


def test_compare_small_reduction():
    out = compare_checks(_states(1), [{"meanAnnualLoss": 100}, {"meanAnnualLoss": 96}])
    assert codes(out) == {"small_reduction"}
    out = compare_checks(_states(1), [{"meanAnnualLoss": 100}, {"meanAnnualLoss": 95}])
    assert codes(out) == set()


def test_compare_cost_exceeds_reduction():
    out = compare_checks(_states(50_000), [{"meanAnnualLoss": 100_000}, {"meanAnnualLoss": 60_000}])
    assert codes(out) == {"cost_exceeds_reduction"}
    assert "($50K) than the average loss it removes ($40K)" in out[0]["message"]


def test_compare_cost_missing():
    out = compare_checks(_states(None), [{"meanAnnualLoss": 100_000}, {"meanAnnualLoss": 50_000}])
    assert codes(out) == {"cost_missing"}


def test_compare_checks_returned_with_run(product_x):
    t = product_x.states[0].model_copy(update={"id": "t", "name": "No change", "cost": None}, deep=True)
    product_x.states.append(t)
    product_x.settings.iterations = 1_000
    res = run_analysis(product_x)
    assert codes(res["comparison"]["checks"]) == {"small_reduction", "cost_missing"}
