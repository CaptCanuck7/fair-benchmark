"""Task 6: first-pass estimates (section 9.6). One structured call, no tools:
the approved scenario and the gathered evidence are in the request.

Validation (schemas.EstimatesOutput, with this request's evidence as context)
holds the model to the rules: every range cites evidence from its own factor
group, obeys the analysis document's units and checks, has low confidence when
its evidence is external only, and the recommended method's factors are each
estimated or listed as unestimated with a data request. Code then sets each
range's basis from the cited evidence's origins.
"""

import json

from pydantic import BaseModel

from app.llm import LLM, LLMResult, untrusted
from app.schemas import FACTOR_GROUPS, EstimatesOutput, EstimatesRequest
from app.tasks.common import load_prompt, render_risk

PROMPT_VERSION = "estimates.v1"


class EstimatesResult(BaseModel):
    method: dict
    estimates: list[dict]
    unestimated: list[dict]


def evidence_context(req: EstimatesRequest) -> dict:
    return {
        "evidence": {e.id: {"origin": e.origin,
                            "groups": {g for g, keys in FACTOR_GROUPS.items() if set(e.factors) & set(keys)}}
                     for e in req.evidence},
        "request_ids": {r.id for r in req.data_requests},
    }


def build_user(req: EstimatesRequest) -> str:
    evidence = [{"id": e.id, "origin": e.origin, "source": e.source_name, "citation": e.citation,
                 "summary": e.summary, "value": e.value, "unit": e.unit, "factors": e.factors, "stale": e.stale}
                for e in req.evidence]
    requests = [{"id": r.id, "team": r.team, "factor": r.factor, "question": r.question, "status": r.status,
                 "answer": r.answer} for r in req.data_requests]
    vectors = req.vectors or {}
    return (
        f"{render_risk(req.risk)}\n\n"
        f"{untrusted('scenario', json.dumps(req.scenario, indent=1, ensure_ascii=False))}\n\n"
        f"{untrusted('scenario', json.dumps({'approved_vectors': vectors.get('paths', [])}, ensure_ascii=False))}\n\n"
        f"{untrusted('evidence', json.dumps(evidence, indent=1, ensure_ascii=False))}\n\n"
        f"Data requests already raised:\n{json.dumps(requests, indent=1, ensure_ascii=False)}\n\n"
        "Recommend the frequency method, propose ranges where the evidence supports them, and return the JSON."
    )


def basis(cited_origins: set[str]) -> str:
    return "mixed" if len(cited_origins) > 1 else next(iter(cited_origins), "internal")


def run(llm: LLM, req: EstimatesRequest) -> LLMResult[EstimatesResult]:
    ctx = evidence_context(req)
    res = llm.structured(load_prompt(PROMPT_VERSION), build_user(req), EstimatesOutput, effort="medium", context=ctx)
    out = res.output
    origins = {e.id: e.origin for e in req.evidence}
    estimates = [{**e.model_dump(), "basis": basis({origins[i] for i in e.evidence_ids if i in origins})}
                 for e in out.estimates]
    result = EstimatesResult(method=out.method.model_dump(), estimates=estimates,
                             unestimated=[u.model_dump() for u in out.unestimated])
    return LLMResult(output=result, usage=res.usage, attempts=res.attempts)
