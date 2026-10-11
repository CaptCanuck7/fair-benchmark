"""Task 2: quality check. The model's half of section 9.1; the rules and the
final status live in api (app/register/quality.py)."""

from app.llm import LLM, LLMResult
from app.schemas import QualityJudgement, QualityRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "quality.v2"


def run(llm: LLM, req: QualityRequest) -> LLMResult[QualityJudgement]:
    rule_gaps = "\n".join(f"- {g.field}: {g.problem}" for g in req.rule_gaps) or "- none"
    user = (
        f"{render_risk(req.risk)}\n\n"
        f"<rule_gaps>\n{rule_gaps}\n</rule_gaps>\n\n"
        "Judge the entry and return the JSON."
    )
    return llm.structured(load_prompt(PROMPT_VERSION), user, QualityJudgement, effort="low")
