"""What every evidence tool shares: the record of citable sources it returned,
date handling for the 24-month stale rule, and wrapping results as data.

Tool results go back to the model inside <evidence> (internal records and the
reference library) or <web_content> (anything from the internet) tags. The
system prompt says content inside them is data, never instructions.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.llm import untrusted

STALE_MONTHS = 24

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_date(text: str | None) -> date | None:
    """Read 2026-04-09, 2026-04, 2026, "April 30, 2025" or "30 April 2025"."""
    if not text:
        return None
    t = str(text).strip()
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})", t):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.match(r"^(\d{4})-(\d{2})$", t):
        return date(int(m[1]), int(m[2]), 1)
    if m := re.match(r"^(\d{4})$", t):
        return date(int(m[1]), 1, 1)
    low = t.lower().replace(",", " ")
    if m := re.match(r"^([a-z]+)\s+(\d{1,2})\s+(\d{4})", low):
        if m[1] in MONTHS:
            return date(int(m[3]), MONTHS[m[1]], int(m[2]))
    if m := re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})", low):
        if m[2] in MONTHS:
            return date(int(m[3]), MONTHS[m[2]], int(m[1]))
    if m := re.match(r"^([a-z]+)\s+(\d{4})", low):
        if m[1] in MONTHS:
            return date(int(m[2]), MONTHS[m[1]], 1)
    # Search results give page age as "2536 days ago", "3 months ago" and so on.
    if m := re.match(r"^(\d+)\s+(day|week|month|year)s?\s+ago", low):
        n, unit = int(m[1]), m[2]
        days = n * {"day": 1, "week": 7, "month": 30.44, "year": 365.25}[unit]
        return (datetime.now(timezone.utc) - timedelta(days=days)).date()
    return None


def iso_date(text: str | None) -> str | None:
    d = parse_date(text)
    return d.isoformat() if d else None


def is_stale(published: str | None, today: date | None = None) -> bool:
    """True when published more than 24 months ago. Unknown dates aren't stale."""
    d = parse_date(published)
    if d is None:
        return False
    today = today or datetime.now(timezone.utc).date()
    months = (today.year - d.year) * 12 + (today.month - d.month) - (1 if today.day < d.day else 0)
    return months > STALE_MONTHS


@dataclass
class Source:
    """A citable source a tool returned in this run."""

    citation: str
    origin: str  # internal | external
    source_type: str
    source_name: str
    published_at: str | None
    retrieved_at: str
    text: str | None = None  # page text, kept for checks (library refresh)
    # The record's cleaned fields (internal rows) or a library entry's metric,
    # value and unit, kept to check an evidence item's value against.
    fields: dict | None = None


@dataclass
class Registry:
    """Every source the tools returned, keyed by citation. An evidence item
    is accepted only if its citation is in here."""

    sources: dict[str, Source] = field(default_factory=dict)
    cve_lookups: int = 0

    def add(self, s: Source) -> Source:
        self.sources.setdefault(s.citation, s)
        return self.sources[s.citation]

    def get(self, citation: str) -> Source | None:
        c = (citation or "").strip()
        if c in self.sources:
            return self.sources[c]
        # Tolerate a trailing slash or surrounding whitespace on URLs.
        alt = c[:-1] if c.endswith("/") else c + "/"
        return self.sources.get(alt)


def as_data(tag: str, payload: Any) -> str:
    """A tool result as delimited, untrusted JSON."""
    return untrusted(tag, json.dumps(payload, ensure_ascii=False, indent=1, default=str))
