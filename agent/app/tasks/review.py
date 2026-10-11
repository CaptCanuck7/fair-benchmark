"""Task 7a: input review (section 9.7). One structured call, no tools.

The analysis, its deterministic checks and any linked evidence are in the
request. Findings are advisory: validation keeps each one tied to a real
option, a factor that option uses, a factor a treatment actually changes, or
evidence that exists.
"""

import json

from app.llm import LLM, LLMResult, untrusted
from app.schemas import ReviewOutput, ReviewRequest
from app.tasks.common import load_prompt

PROMPT_VERSION = "review.v1"


def review_context(req: ReviewRequest) -> dict:
    return {
        "states": {s["id"]: {"baseline": bool(s.get("baseline")),
                             "factors": {f["factor"] for f in s.get("factors", [])},
                             "changed": {c["factor"] for c in s.get("changes", [])}}
                   for s in req.states},
        "evidence": {e["id"] for e in req.evidence},
    }


def build_user(req: ReviewRequest) -> str:
    analysis = {"analysis": req.analysis, "options": req.states}
    parts = [
        untrusted("analysis", json.dumps(analysis, indent=1, ensure_ascii=False)),
        "Deterministic checks already shown to the analyst (don't repeat them):\n"
        + json.dumps(req.checks, indent=1, ensure_ascii=False),
    ]
    if req.evidence:
        parts.append(untrusted("evidence", json.dumps(req.evidence, indent=1, ensure_ascii=False)))
        parts.append("Where each pushed factor came from:\n" + json.dumps(req.provenance, indent=1, ensure_ascii=False))
    else:
        parts.append("This analysis isn't linked to register evidence.")
    parts.append("Review the inputs and return the JSON.")
    return "\n\n".join(parts)


def run(llm: LLM, req: ReviewRequest) -> LLMResult[ReviewOutput]:
    return llm.structured(load_prompt(PROMPT_VERSION), build_user(req), ReviewOutput, effort="medium",
                          context=review_context(req))
