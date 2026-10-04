"""The agent service. Internal only: not published to the host, reached by api.

Task endpoints arrive with milestone 3. Each will take its inputs from api,
run one task function, and return the result for api to store.
"""

import anthropic
from fastapi import FastAPI

from app.config import not_configured_reason, settings

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
        "externalEnabled": settings.external_enabled,
        "allowedDomains": list(settings.allowed_domains),
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
