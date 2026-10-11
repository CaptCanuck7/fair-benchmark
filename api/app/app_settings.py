"""Analyst-editable settings (AGENT_BUILD.md section 12), stored in app_settings.

Each value overrides its .env default. The api applies its own values
(analyst name, triage threshold) to `settings` at startup and on every change.
The agent's values (external sources on or off, extra and removed domains) are
served to the agent from /internal/agent-config at the start of each task.
"""

import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSettingRow

# Values from .env, captured before any override is applied.
ENV_DEFAULTS = {"analyst_name": settings.analyst_name, "triage_min_score": settings.triage_min_score}

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _get(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(AppSettingRow, key)
    return default if row is None else row.value


def _set(session: Session, key: str, value: Any) -> None:
    row = session.get(AppSettingRow, key)
    if row is None:
        session.add(AppSettingRow(key=key, value=value))
    else:
        row.value = value


def apply(session: Session) -> None:
    """Copy stored overrides of api-side values onto `settings`."""
    settings.analyst_name = _get(session, "analyst_name", ENV_DEFAULTS["analyst_name"]) or ""
    settings.triage_min_score = int(_get(session, "triage_min_score", ENV_DEFAULTS["triage_min_score"]))


def agent_overrides(session: Session) -> dict[str, Any]:
    """What the agent merges with its own .env values."""
    return {
        "externalEnabled": _get(session, "external_enabled"),  # None: use .env
        "extraDomains": _get(session, "extra_domains", []) or [],
        "removedDomains": _get(session, "removed_domains", []) or [],
    }


class SettingsError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(message)
        self.path = path


def normalize_domain(d: str) -> str:
    d = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].lstrip(".")
    if not DOMAIN_RE.match(d):
        raise SettingsError("domain", f"“{d}” isn’t a domain name such as example.com.")
    return d


def update(session: Session, changes: dict[str, Any]) -> None:
    """Validate and store changes. Keys: analystName, triageMinScore,
    externalEnabled, extraDomains, removedDomains."""
    if "analystName" in changes:
        name = (changes["analystName"] or "").strip()
        if len(name) > 100:
            raise SettingsError("analystName", "Use at most 100 characters.")
        _set(session, "analyst_name", name)
    if "triageMinScore" in changes:
        v = changes["triageMinScore"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 25:
            raise SettingsError("triageMinScore", "Use a whole number from 1 to 25 (impact × likelihood).")
        _set(session, "triage_min_score", v)
    if "externalEnabled" in changes:
        v = changes["externalEnabled"]
        if v is not None and not isinstance(v, bool):
            raise SettingsError("externalEnabled", "Use true, false or null (follow .env).")
        _set(session, "external_enabled", v)
    for key, store in (("extraDomains", "extra_domains"), ("removedDomains", "removed_domains")):
        if key in changes:
            values = changes[key] or []
            if not isinstance(values, list) or len(values) > 50:
                raise SettingsError(key, "Send a list of at most 50 domains.")
            try:
                _set(session, store, sorted({normalize_domain(str(d)) for d in values}))
            except SettingsError as exc:
                raise SettingsError(key, str(exc)) from exc
    session.commit()
    apply(session)
