"""The triage rule (AGENT_BUILD.md section 9.2). The rule decides; the model
only explains it and may add an advisory note that never changes the status."""

from typing import Any

from app.register.parser import score_input


def would_qualify(baseline_score: int | None, impact: Any, threshold: int) -> bool:
    """Score at or above the threshold, or a baseline impact of 5."""
    return (baseline_score is not None and baseline_score >= threshold) or score_input(impact) == 5


def triage(baseline_score: int | None, impact: Any, threshold: int) -> dict[str, Any]:
    """Status and the rule that produced it. Only for risks the quality check found ready."""
    if baseline_score is not None and baseline_score >= threshold:
        status, rule = "qualifies", f"Baseline score {baseline_score} is at or above the threshold of {threshold}."
    elif score_input(impact) == 5:
        status, rule = "qualifies", "Baseline impact is 5, the highest, so it qualifies whatever its score."
    elif baseline_score is None:
        status, rule = "screened_out", "There is no baseline score to compare with the threshold."
    else:
        status, rule = "screened_out", f"Baseline score {baseline_score} is below the threshold of {threshold}."
    return {"status": status, "score": baseline_score, "threshold": threshold, "rule": rule}
