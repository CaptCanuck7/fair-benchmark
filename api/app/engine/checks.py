"""Pre-run, post-run and comparison checks, ported from the prototype.

Each check is a dict:
    level   "error" | "warn" | "info" | "ok"
    code    stable identifier for the rule
    title   the bold lead-in the prototype shows
    detail  the rest of the sentence
    message title and detail joined, as plain text
    path    the factor it concerns, e.g. "states[1].lef.tef" (when there is one)
Errors block a run; everything else is advice.
"""

from app.content.factors import FORMS, F
from app.engine.distributions import dist_status, is_ok
from app.engine.fmt import every, money, pct
from app.schemas import Dist, State


def _check(level: str, code: str, title: str, detail: str, path: str | None = None, sep: str = ": ") -> dict:
    out = {"level": level, "code": code, "title": title, "detail": detail, "message": f"{title}{sep}{detail}"}
    if path is not None:
        out["path"] = path
    return out


def get_factor(state: State, key: str) -> Dist:
    """Look up a factor by its F key, e.g. "tef" or "primary.response"."""
    obj = state
    for part in F[key]["path"].split("."):
        obj = getattr(obj, part)
    return obj


def factor_path(index: int, key: str) -> str:
    return f"states[{index}].{F[key]['path']}"


def frequency_keys(state: State) -> list[str]:
    """The LEF-side factors the chosen method uses, in display order."""
    lef = state.lef
    if lef.mode == "lef":
        return ["lef"]
    keys = ["cf", "poa"] if lef.mode == "cf_poa" else ["tef"]
    keys += ["tcap", "rs"] if lef.vuln_mode == "tcap_rs" else ["vuln"]
    return keys


# ---------------------------------------------------------------- pre-run

_MISSING = {
    "lef": "Enter a range for loss event frequency.",
    "tef": "Enter a range for threat event frequency.",
    "cf": "Enter a range for contact frequency.",
    "poa": "Enter a range for probability of action.",
    "tcap": "Enter a range for threat capability.",
    "rs": "Enter a range for resistance strength.",
    "vuln": "Enter a range for vulnerability.",
}


def pre_checks(state: State, index: int = 0) -> list[dict]:
    out = []
    for key in frequency_keys(state):
        f = F[key]
        status, msg = dist_status(get_factor(state, key), f["kind"])
        if status != "ok":
            code = "invalid_factor" if status == "error" else "missing_factor"
            out.append(_check("error", code, f["label"], msg if status == "error" else _MISSING[key], factor_path(index, key)))

    for group in ("primary", "secondary"):
        for k, _ in FORMS[group]:
            key = f"{group}.{k}"
            status, msg = dist_status(get_factor(state, key), "money")
            if status == "error":
                title = f"{group.capitalize()} {F[key]['label'].lower()}"
                out.append(_check("error", "invalid_factor", title, msg, factor_path(index, key)))

    slef_status, slef_msg = dist_status(state.slef, "pct")
    if slef_status == "error":
        out.append(_check("error", "invalid_factor", "Secondary loss event frequency", slef_msg, factor_path(index, "slef")))

    if not any(is_ok(getattr(state.primary, k), "money") for k, _ in FORMS["primary"]):
        out.append(_check("error", "no_primary", "Primary loss", "enter at least one form of primary loss.",
                          factor_path(index, "primary.response")))

    has_secondary = any(is_ok(getattr(state.secondary, k), "money") for k, _ in FORMS["secondary"])
    if has_secondary and slef_status == "empty":
        out.append(_check("error", "secondary_without_slef", "Secondary loss",
                          "you entered secondary loss amounts but no secondary loss event frequency. Add it, or clear the amounts.",
                          factor_path(index, "slef")))
    if not has_secondary and slef_status == "ok":
        out.append(_check("warn", "slef_without_secondary", "Secondary loss",
                          "you entered how often stakeholders react but no amounts, so secondary loss is treated as zero.",
                          factor_path(index, "secondary.response")))
    return out


def has_errors(checks: list[dict]) -> bool:
    return any(c["level"] == "error" for c in checks)


# ---------------------------------------------------------------- post-run

def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def post_checks(state: State, r: dict, controls: str = "") -> list[dict]:
    """Checks on a state's results. `r` is the state's result dict from simulate."""
    keys = frequency_keys(state)
    keys += [f"primary.{k}" for k, _ in FORMS["primary"]] + ["slef"] + [f"secondary.{k}" for k, _ in FORMS["secondary"]]
    populated = [(key, F[key], get_factor(state, key)) for key in keys if is_ok(get_factor(state, key), F[key]["kind"])]
    no_src = [f["label"] for _, f, d in populated if not (d.src or "").strip()]
    flat = [f["label"] for _, f, d in populated if d.min == d.max]
    wide = [f["label"] for _, f, d in populated if f["kind"] == "money" and d.min > 0 and d.max / d.min > 100]

    out = []
    lef_mean, mean = r["lefMean"], r["meanAnnualLoss"]
    if lef_mean > 1:
        out.append(_check("warn", "lef_high", "Frequency looks high",
                          f"the model expects {every(lef_mean)}. Check that these are loss events (the organization actually loses something), not attempts or incidents without loss, and compare with your incident history."))
    if 0 < lef_mean < 0.01:
        out.append(_check("info", "lef_rare", "Very rare event",
                          f"{every(lef_mean)}. That can be right, but make sure the range isn’t narrower than your evidence supports."))
    lef = state.lef
    if lef.mode != "lef" and lef.vuln_mode == "direct" and is_ok(lef.vuln, "pct") and lef.vuln.ml >= 50 and (controls or "").strip():
        out.append(_check("warn", "controls_vs_vuln", "Controls vs. vulnerability",
                          "you listed existing controls, but most threat events still succeed (vulnerability most likely ≥ 50%). Either the controls don’t cover this attack path, which is worth saying explicitly, or vulnerability is overstated."))
    if r["derivedVulnerability"] is not None:
        out.append(_check("info", "derived_vuln", "Derived vulnerability",
                          f"threat capability exceeds resistance strength in {pct(r['derivedVulnerability'])} of comparisons. Sense-check it: does it match what you’d have estimated directly?"))
    if r["p50"] == 0 and mean > 0:
        out.append(_check("info", "median_zero", "Most years have no loss",
                          f"the median year is $0 because the event happens in only {pct(r['chanceAnyLoss'])} of years. Report the mean and the tail (90th and 95th percentiles), not the median."))
    if mean > 0 and r["p95"] / mean > 5:
        out.append(_check("info", "heavy_tail", "Heavy tail",
                          f"a 1-in-20 year ({money(r['p95'])}) is more than five times the mean. The mean understates how bad a bad year is, so show both."))
    if r["secondaryShareOfLoss"] > 0.7:
        out.append(_check("info", "secondary_driven", "Secondary loss drives the result",
                          f"{pct(r['secondaryShareOfLoss'])} of simulated loss is secondary. Spend your validation time on the secondary estimates: record counts, notification obligations, contracts and churn."))
    if wide:
        out.append(_check("info", "wide_ranges", "Very wide ranges",
                          f"{', '.join(_dedupe(wide))}. Fine if the uncertainty is real; narrowing them with data would sharpen the result."))
    if flat:
        verb = "have" if len(flat) > 1 else "has"
        out.append(_check("warn", "no_uncertainty", "No uncertainty expressed",
                          f"{', '.join(_dedupe(flat))} {verb} the same minimum and maximum. FAIR depends on honest ranges; a single number hides what you don’t know."))
    if no_src:
        out.append(_check("warn", "undocumented", "Undocumented estimates",
                          f"{len(no_src)} of {len(populated)} factors have no rationale or source recorded. Leadership will ask where the numbers came from."))
    if r["events"] < 50:
        out.append(_check("info", "few_events", "Few simulated events",
                          f"only {r['events']} loss events occurred in the simulation. Increase the number of simulated years for steadier tail percentiles."))
    if not out:
        out.append(_check("ok", "ok", "No problems found.",
                          "The inputs pass the automatic checks. That doesn’t make them right; review each range with the people who own the data.", sep=" "))
    return out


# ---------------------------------------------------------------- compare

def compare_checks(states: list[State], results: list[dict]) -> list[dict]:
    """Checks on each treatment against the current state (index 0)."""
    out = []
    base_mean = results[0]["meanAnnualLoss"]
    for i in range(1, len(states)):
        s, r = states[i], results[i]
        red = base_mean - r["meanAnnualLoss"]
        path = f"states[{i}]"
        if red < 0:
            out.append(_check("warn", "treatment_worse", s.name,
                              "shows more loss than the current state. Check that its inputs reflect the improvement you expect.", path, sep=" "))
        elif base_mean and red / base_mean < 0.05:
            out.append(_check("info", "small_reduction", s.name,
                              "changes average annual loss by less than 5%. Check which factor the fix is meant to change, and whether you changed it.", path, sep=" "))
        if s.cost is not None and s.cost > red:
            out.append(_check("info", "cost_exceeds_reduction", s.name,
                              f"costs more per year ({money(s.cost)}) than the average loss it removes ({money(red)}). It may still be worth it if it cuts the tail: compare the 1-in-20 column.", path, sep=" "))
        if s.cost is None:
            out.append(_check("info", "cost_missing", s.name,
                              "has no annual cost entered, so net benefit can’t be calculated.", path, sep=" "))
    return out
