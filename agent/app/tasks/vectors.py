"""Task 4: attack vectors, or failure paths for non-malicious threat types
(section 9.4). Built from the approved scenario."""

import json

from app.llm import LLM, LLMResult, untrusted
from app.schemas import NON_MALICIOUS, VectorsOutput, VectorsRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "vectors.v1"


def rules(req: VectorsRequest) -> dict:
    """What the output must look like for this request; checked on validation."""
    return {
        "non_malicious": req.scenario.get("threat_type") in NON_MALICIOUS,
        "from_register": bool((req.risk.sections.get("exploit_paths") or "").strip()),
    }


def run(llm: LLM, req: VectorsRequest) -> LLMResult[VectorsOutput]:
    r = rules(req)
    kind = "failure paths" if r["non_malicious"] else "attack vectors"
    source = ("The register entry has exploit paths: restructure them, origin from_register."
              if r["from_register"] else
              "The register entry has no exploit paths: draft up to three, origin agent_drafted.")
    user = (
        f"{render_risk(req.risk)}\n\n"
        f"{untrusted('scenario', json.dumps(req.scenario, indent=2, ensure_ascii=False))}\n\n"
        f"Write {kind}. {source}\nReturn the JSON."
    )
    return llm.structured(load_prompt(PROMPT_VERSION), user, VectorsOutput, effort="medium", context=r)
