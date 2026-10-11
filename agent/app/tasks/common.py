"""Helpers shared by the task modules: prompt loading and rendering the
register entry as delimited, untrusted text."""

from functools import cache
from pathlib import Path

from app.llm import untrusted
from app.schemas import RiskEntry

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

SECTION_LABELS = [
    ("preamble", "Introduction"),
    ("risk_statement", "Risk statement"),
    ("detailed_analysis", "Detailed risk analysis"),
    ("baseline_controls", "Baseline controls"),
    ("exploit_paths", "Exploit paths"),
]


@cache
def load_prompt(version: str) -> str:
    """The system prompt in prompts/{version}.md, e.g. "quality.v1"."""
    return (PROMPTS / f"{version}.md").read_text(encoding="utf-8")


def _value(v: object) -> str:
    return "not recorded" if v is None or (isinstance(v, str) and not v.strip()) else str(v)


def render_risk(risk: RiskEntry) -> str:
    """The entry as labeled plain text inside <register_entry> tags."""
    lines = [
        f"Title: {_value(risk.title)}",
        f"Category: {_value(risk.category)}",
        f"Assets: {', '.join(risk.asset_ids) if risk.asset_ids else 'none listed'}",
        f"Environment: {_value(risk.environment)}",
        f"Risk action: {_value(risk.risk_action)}",
        f"Risk owner: {'recorded (name withheld)' if risk.has_risk_owner else 'not recorded'}",
        f"Baseline impact (1 to 5): {_value(risk.baseline_impact)}",
        f"Baseline likelihood (1 to 5): {_value(risk.baseline_likelihood)}",
        f"Baseline score (impact x likelihood): {_value(risk.baseline_score)}",
        f"Mitigation plan: {_value(risk.mitigation_plan)}",
        "",
    ]
    if risk.structured:
        lines.append("Risk analysis, by section:")
        for key, label in SECTION_LABELS:
            if risk.sections.get(key):
                lines += [f"[{label}]", risk.sections[key], ""]
    else:
        lines += ["Risk analysis (no section labels):", risk.sections.get("raw") or "(empty)"]
    return untrusted("register_entry", "\n".join(lines).strip())
