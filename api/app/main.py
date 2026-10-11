import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import agent_pipeline
from app.config import settings
from app.content.factors import content_payload
from app.db import SessionLocal, init_db
from app.errors import (
    ApiError,
    api_error_handler,
    pydantic_validation_handler,
    request_validation_handler,
)
from app.evidence import EVIDENCE_FILE, load_evidence
from app import app_settings
from app.routers import (
    agent,
    analyses,
    data_requests,
    drafts,
    estimates,
    internal_evidence,
    internal_guard,
    io,
    library,
    register,
    settings as settings_router,
    simulate,
)
from app.routers.analyses import HASH_HEADER


def limit_message(max_bytes: int) -> str:
    return f"The request body is larger than the {max_bytes / (1024 * 1024):g} MB limit."


class BodyTooLarge(HTTPException):
    # An HTTPException, so FastAPI passes it through body parsing as a 413
    # instead of turning it into a generic 400.
    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=limit_message(max_bytes))


class BodySizeLimit:
    """Reject request bodies over the limit with 413, whether or not Content-Length is sent.

    `max_bytes` applies everywhere except the exact paths in `overrides`.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, overrides: dict[str, int] | None = None):
        self.app, self.max_bytes, self.overrides = app, max_bytes, overrides or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        max_bytes = self.overrides.get(scope.get("path", ""), self.max_bytes)
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > max_bytes:
                return await self._reject(send, max_bytes)

        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > max_bytes:
                    raise BodyTooLarge(max_bytes)
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._reject(send, max_bytes)

    async def _reject(self, send: Send, max_bytes: int) -> None:
        body = json.dumps({"detail": limit_message(max_bytes), "errors": []}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as session:
        load_evidence(session, settings.agent_data_dir / EVIDENCE_FILE)
        agent_pipeline.fail_interrupted(session)
        app_settings.apply(session)
        library.seed_library(session, settings.agent_data_dir)
    yield


# No Swagger UI: it loads scripts from a CDN, which the app's CSP blocks. The
# schema itself is served under /api so it is reachable through nginx.
app = FastAPI(
    title="FAIR Risk Workbench API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
    expose_headers=[HASH_HEADER],
)
app.add_middleware(BodySizeLimit, max_bytes=settings.max_body_bytes,
                   overrides={register.IMPORT_PATH: settings.max_upload_bytes})

app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(ValidationError, pydantic_validation_handler)
app.add_exception_handler(ApiError, api_error_handler)

app.include_router(analyses.router)
app.include_router(simulate.router)
app.include_router(io.router)
app.include_router(register.router)
app.include_router(internal_evidence.router)
app.include_router(internal_guard.router)
app.include_router(agent.router)
app.include_router(drafts.router)
app.include_router(estimates.router)
app.include_router(data_requests.router)
app.include_router(library.router)
app.include_router(library.internal)
app.include_router(settings_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/content/factors")
def factors():
    return content_payload()
