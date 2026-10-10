"""Condition classification (sections 6 and 7): which kind of weakness is behind
the risk. Evidence gathering later uses it to choose where to look first."""

from app.llm import LLM, LLMResult
from app.schemas import Classification, ClassifyRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "classify.v1"


def run(llm: LLM, req: ClassifyRequest) -> LLMResult[Classification]:
    user = f"{render_risk(req.risk)}\n\nClassify the condition and return the JSON."
    return llm.structured(load_prompt(PROMPT_VERSION), user, Classification, effort="low")
