"""Monte Carlo simulation of annual loss, vectorized across simulated years.

See CLAUDE.md section 4. Each state is simulated with its own generator
seeded identically (common random numbers), so differences between options
come from their inputs, not from sampling noise.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from app.content.factors import FORMS
from app.engine import stats
from app.engine.checks import compare_checks, has_errors, post_checks, pre_checks
from app.engine.distributions import is_ok, sample_pert
from app.schemas import Analysis, State

EVENT_LIMIT = 20_000_000
TCAP_RS_SAMPLES = 20_000
HIST_SAMPLE_CAP = 200_000


class SimulationError(ValueError):
    """The inputs can't be simulated; the message is safe to show the analyst."""


class PreCheckError(ValueError):
    """At least one state failed its pre-run checks."""

    def __init__(self, checks: list[dict]):
        super().__init__("Fix the input errors before running.")
        self.checks = checks


@dataclass
class StateSim:
    ale: np.ndarray                 # annual loss per simulated year
    lef_y: np.ndarray               # loss event frequency per simulated year
    n_y: np.ndarray                 # loss events per simulated year
    event_loss: np.ndarray          # loss per event, in year order
    derived_vuln: float | None
    form_totals: dict[str, float] = field(default_factory=dict)
    primary_total: float = 0.0
    secondary_total: float = 0.0
    secondary_events: int = 0


def _frequency(rng: np.random.Generator, state: State, n: int) -> tuple[np.ndarray, float | None]:
    lef = state.lef
    if lef.mode == "lef":
        return sample_pert(rng, lef.lef, n), None
    if lef.mode == "cf_poa":
        tef_y = sample_pert(rng, lef.cf, n) * sample_pert(rng, lef.poa, n, 0.01)
    else:
        tef_y = sample_pert(rng, lef.tef, n)
    if lef.vuln_mode == "tcap_rs":
        tcap = sample_pert(rng, lef.tcap, TCAP_RS_SAMPLES)
        rs = sample_pert(rng, lef.rs, TCAP_RS_SAMPLES)
        p = float(np.mean(tcap > rs))
        return tef_y * p, p
    return tef_y * sample_pert(rng, lef.vuln, n, 0.01), None


def simulate_state(state: State, n_years: int, seed: int) -> StateSim:
    """Simulate one state. Assumes it has passed pre_checks()."""
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    lef_y, derived = _frequency(rng, state, n_years)
    n_y = rng.poisson(lef_y)
    total_events = int(n_y.sum())
    if total_events > EVENT_LIMIT:
        raise SimulationError(
            f"{state.name}: this run would simulate {total_events:,} loss events, more than the limit of "
            f"{EVENT_LIMIT:,}. A loss event frequency this high is implausible for a loss event; check that "
            "the frequency counts events where the organization actually loses something, not attempts."
        )
    year_idx = np.repeat(np.arange(n_years), n_y)

    event_loss = np.zeros(total_events)
    totals: dict[str, float] = {}
    for k, _ in FORMS["primary"]:
        d = getattr(state.primary, k)
        if is_ok(d, "money"):
            v = sample_pert(rng, d, total_events)
            totals[f"primary.{k}"] = float(v.sum())
            event_loss += v
    primary_total = float(event_loss.sum())

    secondary = [(k, getattr(state.secondary, k)) for k, _ in FORMS["secondary"]]
    secondary = [(k, d) for k, d in secondary if is_ok(d, "money")]
    secondary_total, secondary_events = 0.0, 0
    if secondary and is_ok(state.slef, "pct"):
        slef_y = sample_pert(rng, state.slef, n_years, 0.01)
        hit = np.flatnonzero(rng.random(total_events) < slef_y[year_idx])
        secondary_events = int(hit.size)
        for k, d in secondary:
            v = sample_pert(rng, d, hit.size)
            totals[f"secondary.{k}"] = float(v.sum())
            secondary_total += float(v.sum())
            event_loss[hit] += v
    else:
        for k, _ in secondary:
            totals[f"secondary.{k}"] = 0.0

    ale = np.bincount(year_idx, weights=event_loss, minlength=n_years)
    return StateSim(ale, lef_y, n_y, event_loss, derived, totals, primary_total, secondary_total, secondary_events)


def summarize(sim: StateSim, threshold: float | None) -> dict:
    """The per-state outputs in CLAUDE.md section 4.4, minus the exceedance curve."""
    n = sim.ale.size
    ale = np.sort(sim.ale)
    lef = np.sort(sim.lef_y)
    single = np.sort(sim.event_loss)
    events = int(single.size)
    loss_total = sim.primary_total + sim.secondary_total
    q = stats.quantile
    return {
        "meanAnnualLoss": float(ale.mean()),
        "p10": q(ale, 0.10),
        "p50": q(ale, 0.50),
        "p90": q(ale, 0.90),
        "p95": q(ale, 0.95),
        "p99": q(ale, 0.99),
        "max": float(ale[-1]),
        "chanceAnyLoss": float(np.count_nonzero(sim.ale > 0) / n),
        "chanceAboveThreshold": float(stats.exceed(ale, threshold)) if threshold else None,
        "lefMean": float(lef.mean()),
        "lefP10": q(lef, 0.10),
        "lefP90": q(lef, 0.90),
        "singleLossMean": float(single.mean()) if events else 0.0,
        "singleLossP10": q(single, 0.10),
        "singleLossP50": q(single, 0.50),
        "singleLossP90": q(single, 0.90),
        "derivedVulnerability": sim.derived_vuln,
        "secondaryShareOfLoss": sim.secondary_total / loss_total if loss_total else 0.0,
        "secondaryShareOfEvents": sim.secondary_events / events if events else 0.0,
        "events": events,
        "breakdown": {k: v / n for k, v in sim.form_totals.items()},
        "histogram": stats.histogram(sim.event_loss[:HIST_SAMPLE_CAP]),
    }


def _comparison(analysis: Analysis, results: list[dict], sorted_ales: list[np.ndarray]) -> dict:
    states, threshold = analysis.states, analysis.settings.threshold
    base = results[0]["meanAnnualLoss"]
    rows = []
    for i, (s, r) in enumerate(zip(states, results)):
        row = {
            "stateId": s.id, "name": s.name,
            "meanAnnualLoss": r["meanAnnualLoss"], "p90": r["p90"], "p95": r["p95"],
            "chanceAboveThreshold": r["chanceAboveThreshold"],
            "cost": s.cost if i else None,
            "reduction": None, "reductionPct": None, "netBenefit": None, "return": None,
        }
        if i:
            red = base - r["meanAnnualLoss"]
            row["reduction"] = red
            row["reductionPct"] = red / base if base else 0.0
            if s.cost is not None:
                row["netBenefit"] = red - s.cost
                if s.cost > 0:
                    row["return"] = red / s.cost
        rows.append(row)
    x_max = stats.curve_x_max(sorted_ales, threshold)
    return {
        "rows": rows,
        "checks": compare_checks(states, results),
        "curves": {
            "xMax": x_max,
            "series": [
                {"stateId": s.id, "name": s.name, "points": stats.exceedance_curve(a, x_max)}
                for s, a in zip(states, sorted_ales)
            ],
        },
    }


def validate_analysis(analysis: Analysis) -> list[dict]:
    """Pre-run checks for every state, each tagged with its state index."""
    out = []
    for i, s in enumerate(analysis.states):
        for c in pre_checks(s, i):
            out.append({**c, "stateIndex": i, "stateId": s.id})
    return out


def run_analysis(analysis: Analysis) -> dict:
    """Run every state with the analysis settings and return the full results.

    Raises PreCheckError if any state has input errors, and SimulationError
    if the inputs would need an implausible number of events.
    """
    checks = validate_analysis(analysis)
    if has_errors(checks):
        raise PreCheckError(checks)

    cfg = analysis.settings
    states_out, sorted_ales = [], []
    for i, s in enumerate(analysis.states):
        sim = simulate_state(s, cfg.iterations, cfg.seed)
        r = summarize(sim, cfg.threshold)
        sorted_ale = np.sort(sim.ale)
        sorted_ales.append(sorted_ale)
        r["exceedanceCurve"] = stats.exceedance_curve(sorted_ale, stats.curve_x_max([sorted_ale], cfg.threshold))
        pre_advice = [c for c in pre_checks(s, i) if c["level"] != "error"]
        r["checks"] = pre_advice + post_checks(s, r, analysis.scope.controls)
        states_out.append({"stateId": s.id, "name": s.name, "cost": s.cost, **r})

    return {
        "runAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "iterations": cfg.iterations,
        "seed": cfg.seed,
        "threshold": cfg.threshold,
        "states": states_out,
        "comparison": _comparison(analysis, states_out, sorted_ales) if len(analysis.states) > 1 else None,
    }
