"""The agent service. Internal only: not published to the host, reached by api.

Each task endpoint takes its inputs from api, runs one task function, and
returns the validated output with the model, prompt version and token counts
for api to store. The agent itself stores nothing.
"""

from collections.abc import Callable

import anthropic
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import api_client
from app.api_client import fetch_config
from app.config import not_configured_reason, settings
from app.guard import OutboundClient
from app.llm import LLM, LLMError, LLMResult
from app.schemas import (
    NON_MALICIOUS,
    ClassifyRequest,
    EvidenceRequest,
    LibraryRequest,
    QualityRequest,
    ScenarioRequest,
    TaskResult,
    TriageRequest,
    VectorsRequest,
)
from app.tasks import classify, evidence, library, quality, scenario, triage, vectors
from app.tools.base import Registry
from app.tools.toolbox import Toolbox

app = FastAPI(title="FAIR workbench agent", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status() -> dict:
    reason = not_configured_reason()
    return {
        "configured": reason is None,
        "reason": reason,
        "model": settings.anthropic_model or None,
        # .env values with the Settings page's overrides applied.
        "externalEnabled": (cfg := fetch_config()).external_enabled,
        "allowedDomains": list(cfg.allowed_domains),
    }


@app.get("/status/check")
def status_check() -> dict:
    """Confirm the key and model work, with a models lookup (no tokens spent)."""
    reason = not_configured_reason()
    if reason:
        return {"ok": False, "reason": reason}
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=15.0, max_retries=1)
        info = client.models.retrieve(settings.anthropic_model)
    except anthropic.AuthenticationError:
        return {"ok": False, "reason": "The Claude API rejected ANTHROPIC_API_KEY."}
    except anthropic.NotFoundError:
        return {"ok": False, "reason": f"The model {settings.anthropic_model!r} wasn’t found."}
    except anthropic.APIError as exc:
        return {"ok": False, "reason": f"The Claude API couldn’t be reached ({exc.__class__.__name__})."}
    return {"ok": True, "model": info.id}


# --- Task endpoints -------------------------------------------------------------


def make_llm() -> LLM:
    """The model client for one task. Replaced in tests."""
    return LLM()


def _run_task(version: str, fn: Callable[[LLM], LLMResult]) -> TaskResult | JSONResponse:
    """Run one task. 503 if the agent isn't configured; 502 if the model call
    failed, with the tokens it spent so api can still record them."""
    reason = not_configured_reason()
    if reason:
        return JSONResponse(status_code=503, content={"detail": reason})
    try:
        result = fn(make_llm())
    except LLMError as exc:
        return JSONResponse(status_code=502, content={
            "detail": str(exc), "prompt_version": version,
            "model": exc.usage.models[-1] if exc.usage.models else settings.anthropic_model,
            "input_tokens": exc.usage.input_tokens, "output_tokens": exc.usage.output_tokens,
        })
    output: BaseModel = result.output
    return TaskResult(
        output=output.model_dump(mode="json"), model=result.model or settings.anthropic_model,
        prompt_version=version, input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens, attempts=result.attempts,
    )


@app.post("/tasks/quality", response_model=TaskResult)
def task_quality(req: QualityRequest):
    return _run_task(quality.PROMPT_VERSION, lambda llm: quality.run(llm, req))


@app.post("/tasks/triage", response_model=TaskResult)
def task_triage(req: TriageRequest):
    return _run_task(triage.PROMPT_VERSION, lambda llm: triage.run(llm, req))


@app.post("/tasks/classify", response_model=TaskResult)
def task_classify(req: ClassifyRequest):
    return _run_task(classify.PROMPT_VERSION, lambda llm: classify.run(llm, req))


@app.post("/tasks/scenario", response_model=TaskResult)
def task_scenario(req: ScenarioRequest):
    return _run_task(scenario.PROMPT_VERSION, lambda llm: scenario.run(llm, req))


@app.post("/tasks/vectors", response_model=TaskResult)
def task_vectors(req: VectorsRequest):
    return _run_task(vectors.PROMPT_VERSION, lambda llm: vectors.run(llm, req))


def make_toolbox(llm: LLM, *, agent_run_id: str | None, asset_ids: list[str], threat_type: str | None,
                 mode: str) -> Toolbox:
    """Tools for one task, behind a guard built for this task: the current
    register identifiers and Settings-page values, logging under its run ID.
    Replaced in tests."""
    config = fetch_config()
    outbound = OutboundClient(api_client.build_guard(config=config), api_client.write_log, agent_run_id=agent_run_id)
    return Toolbox(
        registry=Registry(), outbound=outbound, asset_ids=asset_ids, external=config.external_enabled,
        cve_allowed=threat_type not in NON_MALICIOUS, client=llm.client, model=llm.model,
        allowed_domains=config.allowed_domains, mode=mode,
    )


@app.post("/tasks/evidence", response_model=TaskResult)
def task_evidence(req: EvidenceRequest):
    def go(llm: LLM) -> LLMResult:
        box = make_toolbox(llm, agent_run_id=req.agent_run_id, asset_ids=req.risk.asset_ids,
                           threat_type=req.scenario.get("threat_type"), mode="evidence")
        return evidence.run(llm, req, box)

    return _run_task(evidence.PROMPT_VERSION, go)


@app.post("/tasks/library", response_model=TaskResult)
def task_library(req: LibraryRequest):
    def go(llm: LLM) -> LLMResult:
        box = make_toolbox(llm, agent_run_id=req.agent_run_id, asset_ids=[], threat_type=None, mode="library")
        return library.run(llm, req, box)

    return _run_task(library.PROMPT_VERSION, go)
