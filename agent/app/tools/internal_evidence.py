"""Internal evidence: the mock evidence sheets and the reference library, both
read from api over the internal network. Nothing here reaches the internet,
so these tools work with external sources turned off."""

import re
from collections.abc import Callable
from typing import Any

from app import api_client
from app.tools.base import Registry, Source, as_data, iso_date, now_iso

SHEETS = {
    "assets": "asset",
    "telemetry": "telemetry",
    "incidents": "incident",
    "findings": "finding",
    "control-tests": "control_test",
    "vendors": "vendor",
    "about": "asset",
}
# The column holding a record's date, per sheet, for the stale check.
DATE_COLUMNS = ("Date", "First Seen", "Last Security Assessment", "Latest SOC 2 Period End")
EMPTY_COLUMN = re.compile(r"^Column \d+$")


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop the spreadsheet's empty trailing columns."""
    return {k: v for k, v in fields.items() if v not in (None, "") and not EMPTY_COLUMN.match(k)}


def _source_type(sheet: str, fields: dict[str, Any]) -> str:
    if sheet == "control-tests" and "penetration" in str(fields.get("Activity", "")).lower():
        return "pen_test"
    return SHEETS[sheet]


def records(registry: Registry, sheets: list[str], asset_ids: list[str], incident_type: str | None = None,
            fetch: Callable[..., dict] = api_client.internal_records) -> str:
    """Rows from the named sheets for the risk's assets (plus organization-wide
    rows). With `incident_type`, incidents of that type across all assets."""
    out = []
    for sheet in sheets:
        if sheet not in SHEETS:
            out.append({"sheet": sheet, "error": f"Unknown sheet. Use one of: {', '.join(SHEETS)}."})
            continue
        if incident_type and sheet == "incidents":
            data = fetch(sheet, None, incident_type)
        else:
            data = fetch(sheet, None if sheet == "about" else asset_ids)
        rows = []
        for item in data["items"]:
            fields = _clean(item["fields"])
            published = next((iso_date(str(fields[c])) for c in DATE_COLUMNS if c in fields), None)
            registry.add(Source(citation=item["citation"], origin="internal", source_type=_source_type(sheet, fields),
                                source_name=data["sheet"], published_at=published, retrieved_at=now_iso()))
            rows.append({"citation": item["citation"], "organizationWide": item.get("organizationWide", False),
                         "fields": fields})
        out.append({"sheet": data["sheet"], "rows": rows, "note": None if rows else "No rows for these assets."})
    return as_data("evidence", out)


def library(registry: Registry, query: str, search: Callable[..., list[dict]] = api_client.library_search) -> str:
    """Approved reference library figures matching the query."""
    entries = search(query)
    out = []
    for e in entries:
        registry.add(Source(citation=e["citation"], origin="external", source_type="report",
                            source_name=f"{e['source']} {e['edition']}", published_at=iso_date(e["edition"]),
                            retrieved_at=e.get("retrievedAt") or now_iso()))
        out.append({"citation": e["citation"], "metric": e["metric"], "value": e["value"], "unit": e["unit"],
                    "segment": e.get("segment"), "source": e["source"], "edition": e["edition"],
                    "page": e.get("page")})
    note = None if out else ("No approved library entries match. The library starts empty; an analyst adds or "
                             "approves entries on the Settings page.")
    return as_data("evidence", {"entries": out, "note": note})
