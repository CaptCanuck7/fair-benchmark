"""Calls from api to the agent service's task endpoints (internal network only)."""

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

# Long enough for a model call with one corrective retry.
TASK_TIMEOUT = 300.0


@dataclass
class TaskResult:
    output: dict[str, Any]
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int


@dataclass
class AgentCallError(Exception):
    """A task that didn't return a result. `message` is safe to show the analyst."""

    message: str
    usage: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def call_task(task: str, payload: dict[str, Any]) -> TaskResult:
    """POST to /tasks/{task} on the agent. Raises AgentCallError on any failure."""
    try:
        res = httpx.post(f"{settings.agent_url}/tasks/{task}", json=payload, timeout=TASK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AgentCallError(f"The agent service couldn’t be reached ({exc.__class__.__name__}).") from exc
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code != 200:
        detail = body.get("detail") if isinstance(body.get("detail"), str) else f"status {res.status_code}"
        raise AgentCallError(detail, {k: body.get(k) for k in ("model", "prompt_version", "input_tokens", "output_tokens")})
    return TaskResult(
        output=body["output"], model=body.get("model", ""), prompt_version=body.get("prompt_version", ""),
        input_tokens=int(body.get("input_tokens") or 0), output_tokens=int(body.get("output_tokens") or 0),
    )


NOT_RUNNING = "The agent service isn’t running. Start it with docker compose up."


def fetch_agent_status() -> dict:
    """Ask the agent service whether it is configured. Never raises."""
    try:
        res = httpx.get(f"{settings.agent_url}/status", timeout=3.0)
        res.raise_for_status()
        data = res.json()
    except (httpx.HTTPError, ValueError):
        return {"configured": False, "reason": NOT_RUNNING, "model": None, "externalEnabled": False}
    return {
        "configured": bool(data.get("configured")),
        "reason": data.get("reason"),
        "model": data.get("model"),
        "externalEnabled": bool(data.get("externalEnabled")),
        "allowedDomains": data.get("allowedDomains", []),
    }
