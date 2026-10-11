"""Task 7b: report drafting (section 9.7). One structured call, no tools.

The api sends one stored run's figures, already formatted. Validation makes
the model copy them exactly and write no other numbers, with the usual single
retry; the api then checks every number against the stored run itself and
discards the draft on any mismatch.
"""

import json

from app.llm import LLM, LLMResult, untrusted
from app.schemas import ReportOutput, ReportRequest, figures_in
from app.tasks.common import load_prompt

PROMPT_VERSION = "report.v1"


def report_context(req: ReportRequest) -> dict:
    texts: list[str] = [str(v) for v in req.run.values() if v]
    for o in req.options:
        texts += [str(v) for v in (o.get("figures") or {}).values()]
        texts += [str(v) for v in (o.get("compared_with_current") or {}).values()]
        texts += [str(c) for c in o.get("checks") or []]
    names = [str(req.analysis.get("title") or "")] + [str(o.get("name") or "") for o in req.options]
    return {"figures": {f for t in texts for f in figures_in(t)}, "names": names,
            "residual": req.residual_state_id is not None}


def build_user(req: ReportRequest) -> str:
    context = {"analysis": req.analysis, "register_risk": req.risk}
    figures = {"run": req.run, "options": req.options, "residual_state_id": req.residual_state_id}
    return (
        f"{untrusted('analysis', json.dumps(context, indent=1, ensure_ascii=False))}\n\n"
        f"Figures from the stored run (copy them exactly):\n{json.dumps(figures, indent=1, ensure_ascii=False)}\n\n"
        "Draft the report and return the JSON."
    )


def run(llm: LLM, req: ReportRequest) -> LLMResult[ReportOutput]:
    return llm.structured(load_prompt(PROMPT_VERSION), build_user(req), ReportOutput, effort="medium",
                          context=report_context(req))
