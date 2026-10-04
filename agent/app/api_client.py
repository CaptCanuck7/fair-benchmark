"""Calls from the agent to the api's internal endpoints.

The agent holds no state. The api owns the database, including the outbound
log and the identifiers the guard blocks.
"""

import httpx

from app.config import settings
from app.guard import Guard, Identifier, LogEntry


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.api_url, timeout=10.0)


def fetch_identifiers() -> list[Identifier]:
    with _client() as c:
        res = c.get("/internal/guard/identifiers")
        res.raise_for_status()
        return [Identifier(kind=i["kind"], value=i["value"]) for i in res.json()]


def write_log(entry: LogEntry) -> None:
    """Store one outbound attempt. Raises if the api can't store it, so the
    request it describes is not sent."""
    with _client() as c:
        res = c.post("/internal/outbound-log", json={
            "agent_run_id": entry.agent_run_id,
            "tool": entry.tool,
            "destination": entry.destination[:2048],
            "query": entry.query[:2048] if entry.query else entry.query,
            "allowed": entry.allowed,
            "blocked_reason": entry.blocked_reason,
        })
        res.raise_for_status()


def build_guard(approved_queries: tuple[str, ...] = (), vendor_names: tuple[str, ...] = ()) -> Guard:
    """A guard with the current denylist. Built per task, so a new register
    import is picked up on the next task."""
    return Guard(
        allowed_domains=settings.allowed_domains,
        identifiers=fetch_identifiers(),
        external_enabled=settings.external_enabled,
        vendor_names=vendor_names,
        approved_queries=approved_queries,
    )
