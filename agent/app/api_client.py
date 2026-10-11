"""Calls from the agent to the api's internal endpoints.

The agent holds no state. The api owns the database, including the outbound
log, the identifiers the guard blocks, the Settings-page overrides, the mock
internal evidence and the reference library.
"""

from dataclasses import dataclass

import httpx

from app.config import settings
from app.guard import Guard, Identifier, LogEntry


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.api_url, timeout=10.0)


@dataclass(frozen=True)
class EffectiveConfig:
    """.env values with the Settings page's overrides applied."""

    external_enabled: bool
    allowed_domains: tuple[str, ...]


def fetch_config() -> EffectiveConfig:
    """Merge the api's overrides with .env. If the api can't be reached, use
    .env alone (the api being down also stops every task that needs it)."""
    try:
        with _client() as c:
            res = c.get("/internal/guard/agent-config")
            res.raise_for_status()
            o = res.json()
    except (httpx.HTTPError, ValueError):
        o = {}
    removed = set(o.get("removedDomains") or [])
    domains = [d for d in settings.allowed_domains if d not in removed]
    domains += [d for d in o.get("extraDomains") or [] if d not in domains]
    external = o.get("externalEnabled")
    return EffectiveConfig(
        external_enabled=settings.external_enabled if external is None else bool(external),
        allowed_domains=tuple(domains),
    )


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


def build_guard(approved_queries: tuple[str, ...] = (), vendor_names: tuple[str, ...] = (),
                config: EffectiveConfig | None = None) -> Guard:
    """A guard with the current denylist and settings. Built per task, so a new
    register import or a Settings change is picked up on the next task."""
    config = config or fetch_config()
    return Guard(
        allowed_domains=config.allowed_domains,
        identifiers=fetch_identifiers(),
        external_enabled=config.external_enabled,
        vendor_names=vendor_names,
        approved_queries=approved_queries,
    )


def internal_records(sheet: str, asset_ids: list[str] | None = None, incident_type: str | None = None) -> dict:
    """Rows from one mock evidence sheet (read-only, internal network only)."""
    params: list[tuple[str, str]] = [("asset_id", a) for a in asset_ids or []]
    if incident_type:
        params.append(("type", incident_type))
    with _client() as c:
        res = c.get(f"/internal/evidence/{sheet}", params=params)
        res.raise_for_status()
        return res.json()


def library_search(query: str, limit: int = 10) -> list[dict]:
    """Approved reference library entries matching the query."""
    with _client() as c:
        res = c.get("/internal/library", params={"q": query, "limit": limit})
        res.raise_for_status()
        return res.json()
