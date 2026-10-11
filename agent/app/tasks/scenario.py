"""Task 3: scenario scoping (section 9.3). One default loss-event scenario,
with each baseline control mapped to the factor it affects."""

from app.llm import LLM, LLMResult
from app.schemas import Scenario, ScenarioRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "scenario.v1"


def run(llm: LLM, req: ScenarioRequest) -> LLMResult[Scenario]:
    hint = ""
    if req.classification:
        c = req.classification
        kinds = c.primary_type + (f" (also {c.secondary_type})" if c.secondary_type else "")
        hint = f"The condition has been classified as: {kinds}.\n\n"
    user = f"{render_risk(req.risk)}\n\n{hint}Draft the default scenario and return the JSON."
    return llm.structured(load_prompt(PROMPT_VERSION), user, Scenario, effort="medium")
