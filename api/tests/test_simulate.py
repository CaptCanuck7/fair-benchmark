import math
import time

import numpy as np
import pytest

from app.engine.simulate import (
    EVENT_LIMIT,
    PreCheckError,
    SimulationError,
    run_analysis,
    simulate_state,
    summarize,
)
from app.engine.stats import CURVE_POINTS, HIST_BINS, nice_max
from app.schemas import Analysis, State
from conftest import dist, simple_state

N = 100_000


def fixed_state(lef=0.5, loss=100_000) -> State:
    s = State()
    s.lef.mode = "lef"
    s.lef.lef = dist(lef, lef, lef)
    s.primary.response = dist(loss, loss, loss)
    return s


def run_state(state: State, n=N, seed=20260930, threshold=None) -> dict:
    return summarize(simulate_state(state, n, seed), threshold)


# ---------------------------------------------------------------- basics

def test_deterministic_case():
    r = run_state(fixed_state())
    assert r["meanAnnualLoss"] == pytest.approx(50_000, rel=0.02)
    assert r["chanceAnyLoss"] == pytest.approx(1 - math.exp(-0.5), abs=0.01)
    assert r["singleLossP50"] == 100_000
    assert r["breakdown"] == {"primary.response": pytest.approx(r["meanAnnualLoss"])}


def test_same_seed_is_identical(product_x):
    a = run_analysis(product_x)
    b = run_analysis(product_x)
    for k in ("meanAnnualLoss", "p90", "p99", "max", "events", "singleLossP50"):
        assert a["states"][0][k] == b["states"][0][k]


def test_different_seeds_agree_within_3pct(product_x):
    a = run_analysis(product_x)["states"][0]["meanAnnualLoss"]
    product_x.settings.seed = 12345
    b = run_analysis(product_x)["states"][0]["meanAnnualLoss"]
    assert a != b
    assert abs(a - b) / a < 0.03


# ---------------------------------------------------------------- reference case

def test_product_x_reference_ranges(product_x):
    r = run_analysis(product_x)["states"][0]
    assert 225_000 <= r["meanAnnualLoss"] <= 260_000
    assert 0.175 <= r["chanceAnyLoss"] <= 0.205
    assert 1_080_000 <= r["p90"] <= 1_300_000
    assert 0.20 <= r["lefMean"] <= 0.23
    assert 1_050_000 <= r["singleLossP50"] <= 1_300_000
    assert 0.70 <= r["secondaryShareOfLoss"] <= 0.82


def test_product_x_outputs_shape(product_x):
    product_x.settings.threshold = 1_000_000
    r = run_analysis(product_x)["states"][0]
    assert r["derivedVulnerability"] is None
    assert 0 < r["chanceAboveThreshold"] < r["chanceAnyLoss"]
    assert r["p10"] <= r["p50"] <= r["p90"] <= r["p95"] <= r["p99"] <= r["max"]
    assert set(r["breakdown"]) == {
        "primary.response", "primary.replacement",
        "secondary.response", "secondary.fines", "secondary.reputation",
    }
    assert sum(r["breakdown"].values()) == pytest.approx(r["meanAnnualLoss"])

    curve = r["exceedanceCurve"]
    assert len(curve) == CURVE_POINTS
    assert curve[0]["x"] == 0 and curve[0]["y"] == pytest.approx(r["chanceAnyLoss"])
    assert curve[-1]["x"] >= 1_000_000 * 1.15
    assert all(p["y"] >= q["y"] for p, q in zip(curve, curve[1:]))

    hist = r["histogram"]
    assert len(hist["bins"]) == HIST_BINS
    assert hist["total"] == min(r["events"], 200_000)
    assert sum(b["count"] for b in hist["bins"]) == hist["total"]


# ---------------------------------------------------------------- frequency methods

def test_tcap_rs_derived_vulnerability():
    s = simple_state()
    s.lef.mode = "tef_vuln"
    s.lef.vuln_mode = "tcap_rs"
    s.lef.tef = dist(1, 2, 4)
    s.lef.tcap = dist(40, 60, 80)
    s.lef.rs = dist(50, 70, 90)
    r = run_state(s)
    assert 0.15 <= r["derivedVulnerability"] <= 0.22
    # Every year uses the same scalar vulnerability.
    s.lef.tef = dist(2, 2, 2)
    sim = simulate_state(s, 1000, 1)
    assert np.all(sim.lef_y == 2 * sim.derived_vuln)


def test_thinning_matches_expected_event_count():
    s = simple_state()
    s.lef.mode = "tef_vuln"
    s.lef.vuln_mode = "direct"
    s.lef.tef = dist(1, 4, 12)
    s.lef.vuln = dist(5, 20, 50)
    sim = simulate_state(s, N, 99)
    assert sim.n_y.mean() == pytest.approx(sim.lef_y.mean(), rel=0.02)


def test_cf_poa_frequency():
    s = simple_state()
    s.lef.mode = "cf_poa"
    s.lef.vuln_mode = "direct"
    s.lef.cf = dist(10, 10, 10)
    s.lef.poa = dist(20, 20, 20)
    s.lef.vuln = dist(50, 50, 50)
    r = run_state(s)
    assert r["lefMean"] == pytest.approx(10 * 0.2 * 0.5)


# ---------------------------------------------------------------- secondary loss

def test_secondary_needs_both_slef_and_amounts():
    s = fixed_state()
    s.slef = dist(100, 100, 100)
    r = run_state(s)
    assert r["secondaryShareOfLoss"] == 0

    s.secondary.fines = dist(300_000, 300_000, 300_000)
    r = run_state(s)
    assert r["singleLossP50"] == 400_000
    assert r["secondaryShareOfLoss"] == pytest.approx(0.75)
    assert r["secondaryShareOfEvents"] == 1


def test_secondary_trigger_rate():
    s = fixed_state(lef=2)
    s.slef = dist(25, 25, 25)
    s.secondary.response = dist(1_000, 1_000, 1_000)
    r = run_state(s)
    assert r["secondaryShareOfEvents"] == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------- runs and limits

def test_comparison_uses_common_random_numbers(product_x):
    treat = product_x.states[0].model_copy(deep=True)
    treat.id, treat.name, treat.cost = "t1", "Better WAF", 20_000
    treat.lef.vuln = dist(1, 4, 10)
    product_x.states.append(treat)
    product_x.settings.iterations = 10_000

    res = run_analysis(product_x)
    rows = res["comparison"]["rows"]
    base, t = rows[0]["meanAnnualLoss"], rows[1]["meanAnnualLoss"]
    assert t < base
    assert rows[1]["reduction"] == pytest.approx(base - t)
    assert rows[1]["reductionPct"] == pytest.approx((base - t) / base)
    assert rows[1]["netBenefit"] == pytest.approx(base - t - 20_000)
    assert rows[1]["return"] == pytest.approx((base - t) / 20_000)
    assert rows[0]["reduction"] is None

    curves = res["comparison"]["curves"]
    assert len(curves["series"]) == 2
    assert curves["series"][0]["points"][-1]["x"] == curves["series"][1]["points"][-1]["x"] == curves["xMax"]

    # An identical treatment gives identical results.
    product_x.states[1] = product_x.states[0].model_copy(update={"id": "t2", "name": "Same"})
    rows = run_analysis(product_x)["comparison"]["rows"]
    assert rows[0]["meanAnnualLoss"] == rows[1]["meanAnnualLoss"]


def test_run_blocks_on_pre_check_errors():
    a = Analysis()  # blank: nothing entered
    with pytest.raises(PreCheckError) as exc:
        run_analysis(a)
    paths = {c["path"] for c in exc.value.checks}
    assert "states[0].lef.tef" in paths and "states[0].lef.vuln" in paths


def test_event_limit():
    s = fixed_state(lef=EVENT_LIMIT / 1000 * 2)
    with pytest.raises(SimulationError, match="implausible"):
        simulate_state(s, 1000, 1)


def test_no_loss_case():
    s = fixed_state(lef=0)
    r = run_state(s, n=1000)
    assert r["meanAnnualLoss"] == 0 and r["events"] == 0 and r["histogram"] is None


@pytest.mark.parametrize("v,expected", [
    (0, 1), (-5, 1), (0.7, 1), (1, 1), (1.2, 2), (2, 2), (2.2, 2.5), (3, 5), (5, 5), (5.1, 10),
    (1234, 2000), (250_000, 250_000), (260_000, 500_000), (9.9e6, 1e7),
])
def test_nice_max(v, expected):
    assert nice_max(v) == pytest.approx(expected)


def test_performance_four_states_high_frequency():
    a = Analysis()
    a.settings.iterations = 100_000
    states = []
    for i in range(4):
        s = simple_state()
        s.id = f"s{i}"
        s.lef.lef = dist(20, 40, 50 + i)
        s.primary.productivity = dist(1_000, 5_000, 20_000)
        s.primary.replacement = dist(1_000, 5_000, 20_000)
        s.slef = dist(10, 30, 60)
        s.secondary.response = dist(1_000, 5_000, 20_000)
        s.secondary.fines = dist(0, 5_000, 50_000)
        s.secondary.competitive = dist(0, 5_000, 50_000)
        s.secondary.reputation = dist(0, 5_000, 50_000)
        states.append(s)
    a.states = states
    t0 = time.perf_counter()
    run_analysis(a)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5, f"run took {elapsed:.1f}s"
