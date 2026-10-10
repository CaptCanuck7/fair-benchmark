"""The deterministic layer of the quality check (AGENT_BUILD.md section 9.1).

These rules run before the model. They find fields that are missing and
analysis text that is unstructured or too short. Some gaps block the risk
(`needs_info`) whatever the model thinks:

- Missing impact, likelihood or risk statement always blocks.
- Missing assets or environment blocks only a risk that would qualify for
  quantification (score at or above the triage threshold, or impact 5). A
  low-scoring risk is screened out by triage anyway, so asking for its assets
  first would be busywork. Its gaps are still listed. (Decision recorded in
  the README: this is what makes TR-16 ready, as section 14 expects.)

The model then judges the analysis text (agent task "quality"), and
`combine()` merges both layers into the stored result. The model's three
checks (names an asset, a condition, a loss path) follow the same threshold:
they block a risk that would qualify, and are listed but don't block one that
wouldn't.
"""

from dataclasses import asdict, dataclass
from typing import Any

from app.register.parser import score_input

MIN_ANALYSIS_CHARS = 200

ALWAYS_BLOCKING = frozenset({"baseline_impact", "baseline_likelihood", "risk_statement"})
BLOCKING_IF_QUALIFYING = frozenset({"assets", "environment"})


@dataclass(frozen=True)
class Gap:
    field: str
    problem: str
    source: str = "rule"  # "rule" or "agent"


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def rule_gaps(fields: dict[str, Any], sections: dict[str, str], structured: bool) -> list[Gap]:
    """Every deterministic gap, in register column order."""
    gaps: list[Gap] = []
    if not fields.get("asset_ids"):
        gaps.append(Gap("assets", "No assets are listed."))
    if _blank(fields.get("environment")):
        gaps.append(Gap("environment", "No environment is named."))
    if _blank(fields.get("risk_owner")):
        gaps.append(Gap("risk_owner", "No risk owner is named."))
    for key, label in (("baseline_impact", "impact"), ("baseline_likelihood", "likelihood")):
        if score_input(fields.get(key)) is None:
            problem = f"No baseline {label} score." if _blank(fields.get(key)) else \
                f"The baseline {label} isn’t a whole number from 1 to 5."
            gaps.append(Gap(key, problem))
    if _blank(fields.get("risk_action")):
        gaps.append(Gap("risk_action", "No risk action (for example Mitigate or Accept) is recorded."))

    text = "\n".join(v for v in sections.values() if v)
    if not structured:
        gaps.append(Gap("risk_statement", "There is no risk statement: the analysis has none of the section labels."))
        gaps.append(Gap("risk_analysis", "The analysis isn’t split into the standard sections (Risk Statement, "
                                         "Detailed Risk Analysis, Baseline Controls)."))
    elif _blank(sections.get("risk_statement")):
        gaps.append(Gap("risk_statement", "The analysis has no Risk Statement section."))
    if len(text.strip()) < MIN_ANALYSIS_CHARS:
        gaps.append(Gap("risk_analysis", f"The analysis is only {len(text.strip())} characters long, "
                                         f"too short to describe the risk (at least {MIN_ANALYSIS_CHARS} expected)."))
    return gaps


def blocking_gaps(gaps: list[Gap], would_qualify: bool) -> list[Gap]:
    """The gaps that make a risk needs_info whatever the model's view."""
    return [g for g in gaps if g.field in ALWAYS_BLOCKING or (would_qualify and g.field in BLOCKING_IF_QUALIFYING)]


def combine(gaps: list[Gap], would_qualify: bool, judgement: dict[str, Any]) -> dict[str, Any]:
    """Merge the rules with the model's judgement into the stored quality result.

    `judgement` is the agent's quality output: names_asset, names_condition,
    names_loss_path, gaps [{field, problem}] and questions.
    """
    blocking = blocking_gaps(gaps, would_qualify)
    missing = [name for name, key in (("asset", "names_asset"), ("condition", "names_condition"),
                                      ("loss_path", "names_loss_path")) if not judgement.get(key)]
    blocking_checks = missing if would_qualify else []
    status = "needs_info" if blocking or blocking_checks else "ready"

    rule_fields = {(g.field, g.problem) for g in gaps}
    agent_gaps = [Gap(str(g["field"]), str(g["problem"]), "agent") for g in judgement.get("gaps", [])
                  if (g.get("field"), g.get("problem")) not in rule_fields]
    return {
        "status": status,
        "gaps": [asdict(g) | {"blocking": g in blocking} for g in gaps] +
                [asdict(g) | {"blocking": False} for g in agent_gaps],
        "questions": list(judgement.get("questions", [])),
        "checks": {
            "namesAsset": bool(judgement.get("names_asset")),
            "namesCondition": bool(judgement.get("names_condition")),
            "namesLossPath": bool(judgement.get("names_loss_path")),
        },
        "blockedBy": sorted({g.field for g in blocking}) + [f"agent:{m}" for m in blocking_checks],
        "unmetChecks": missing,
        "wouldQualify": would_qualify,
    }
