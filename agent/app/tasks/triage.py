"""Task 1: triage. The rule in api decides the status; the model only writes
the reason and an optional advisory note (section 9.2)."""

from app.llm import LLM, LLMResult
from app.schemas import TriageNote, TriageRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "triage.v1"


def run(llm: LLM, req: TriageRequest) -> LLMResult[TriageNote]:
    rule = req.rule
    decision = "qualifies for quantification" if rule.status == "qualifies" else "is screened out"
    user = (
        f"{render_risk(req.risk)}\n\n"
        "<triage_rule>\n"
        f"Decision: this risk {decision}.\n"
        f"Rule: {rule.rule}\n"
        f"Baseline score: {rule.score if rule.score is not None else 'none'}; threshold: {rule.threshold}.\n"
        "</triage_rule>\n\n"
        "Explain the decision and return the JSON."
    )
    return llm.structured(load_prompt(PROMPT_VERSION), user, TriageNote, effort="low")
