import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.content.factors import content_payload
from app.db import init_db
from app.errors import (
    ApiError,
    api_error_handler,
    pydantic_validation_handler,
    request_validation_handler,
)
from app.routers import analyses, io, simulate
from app.routers.analyses import HASH_HEADER


LIMIT_MESSAGE = "The request body is larger than the 1 MB limit."


class BodyTooLarge(HTTPException):
    # An HTTPException, so FastAPI passes it through body parsing as a 413
    # instead of turning it into a generic 400.
    def __init__(self) -> None:
        super().__init__(status_code=413, detail=LIMIT_MESSAGE)


class BodySizeLimit:
    """Reject request bodies over `max_bytes` with 413, whether or not Content-Length is sent."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                return await self._reject(send)

        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge()
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
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": LIMIT_MESSAGE, "errors": []}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
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
app.add_middleware(BodySizeLimit, max_bytes=settings.max_body_bytes)

app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(ValidationError, pydantic_validation_handler)
app.add_exception_handler(ApiError, api_error_handler)

app.include_router(analyses.router)
app.include_router(simulate.router)
app.include_router(io.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/content/factors")
def factors():
    return content_payload()
