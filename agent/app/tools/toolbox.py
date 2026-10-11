"""The tools a task may use, as Claude tool definitions plus a dispatcher.

Which tools are offered depends on the task (AGENT_BUILD.md section 7):
- Internal records and the reference library: always.
- MITRE ATT&CK and allowlisted web search and fetch: when external sources are on.
- NVD, CISA KEV and EPSS: when external sources are on and the scenario's
  threat type is malicious. Accidental, failure and natural threats get no
  CVE lookups, so those tools aren't offered at all.
"""

from collections.abc import Callable
from typing import Any

import httpx

from app import api_client
from app.guard import Blocked, OutboundClient
from app.tools import attack, epss, internal_evidence, kev, nvd, web
from app.tools.base import Registry

SHEET_NAMES = list(internal_evidence.SHEETS)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required,
                             "additionalProperties": False}}


DEFS = {
    "internal_records": _tool(
        "internal_records",
        "Read internal evidence records for this risk's assets (plus organization-wide records). Sheets: assets "
        "(record and customer counts, data held), telemetry (alert and attempt counts), incidents (past events and "
        "their costs), findings (scanner and assessment findings), control-tests (control tests, audits, "
        "penetration tests), vendors (third-party assessments), about (the loaded labor rate for response hours). "
        "Set incident_type (for example 'phishing') to find incidents of that type on any asset.",
        {"sheets": {"type": "array", "items": {"type": "string", "enum": SHEET_NAMES}, "minItems": 1},
         "incident_type": {"type": ["string", "null"]}},
        ["sheets"],
    ),
    "library_lookup": _tool(
        "library_lookup",
        "Search the approved reference library: figures from annual reports (Verizon DBIR, IBM Cost of a Data "
        "Breach, Cyentia IRIS) such as cost per record or breach frequency. Use it instead of searching the web "
        "for report figures.",
        {"query": {"type": "string"}}, ["query"],
    ),
    "attack_techniques": _tool(
        "attack_techniques",
        "Search MITRE ATT&CK techniques by descriptive words, for a missing control or an attack vector.",
        {"keywords": {"type": "string"}}, ["keywords"],
    ),
    "nvd_search": _tool(
        "nvd_search",
        "Search the National Vulnerability Database for vulnerabilities in a named product and version, for "
        "example 'Windows Server 2012 R2'. Product names only: never internal names or IDs.",
        {"keyword": {"type": "string"}}, ["keyword"],
    ),
    "kev_check": _tool(
        "kev_check",
        "Check CVE IDs against the CISA Known Exploited Vulnerabilities catalog.",
        {"cve_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}}, ["cve_ids"],
    ),
    "epss_scores": _tool(
        "epss_scores",
        "Get EPSS scores (probability of exploitation in the next 30 days) for CVE IDs.",
        {"cve_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}}, ["cve_ids"],
    ),
    "web_search": _tool(
        "web_search",
        "Search allowlisted public sites. Use short, generic queries of at most 120 characters, such as 'TLS 1.0 "
        "interception risk' or 'end-of-support operating system exploitation rates'. Never include names, IDs, "
        "business units, environments or other details from the register or internal records: such queries are "
        "blocked.",
        {"query": {"type": "string"}}, ["query"],
    ),
    "web_fetch": _tool(
        "web_fetch",
        "Read one page from an allowlisted site as text, for example a vendor advisory or a report's web page.",
        {"url": {"type": "string"}}, ["url"],
    ),
}


class Toolbox:
    def __init__(self, *, registry: Registry, outbound: OutboundClient | None, asset_ids: list[str],
                 external: bool, cve_allowed: bool, client: Any = None, model: str = "",
                 allowed_domains: tuple[str, ...] = (), mode: str = "evidence",
                 internal_fetch: Callable[..., dict] = api_client.internal_records,
                 library_search: Callable[..., list[dict]] = api_client.library_search,
                 attack_index: list[dict] | None = None):
        self.registry, self.outbound, self.asset_ids = registry, outbound, asset_ids
        self.client, self.model, self.allowed_domains, self.mode = client, model, allowed_domains, mode
        self.internal_fetch, self.library_search, self.attack_index = internal_fetch, library_search, attack_index
        if mode == "library":
            self.names = ["web_search", "web_fetch"] if external else []
        else:
            self.names = ["internal_records", "library_lookup"]
            if external:
                self.names += ["attack_techniques"]
                if cve_allowed:
                    self.names += ["nvd_search", "kev_check", "epss_scores"]
                self.names += ["web_search", "web_fetch"]

    def definitions(self) -> list[dict]:
        return [DEFS[n] for n in self.names]

    def execute(self, name: str, args: dict) -> tuple[str, bool]:
        if name not in self.names:
            return f"The tool {name} isn't available for this task.", True
        try:
            return self._run(name, args), False
        except Blocked as exc:
            return web.blocked_message(exc.reason), True
        except httpx.HTTPError as exc:
            return f"The source couldn't be reached ({exc.__class__.__name__}). Try another source.", True
        except (KeyError, ValueError, TypeError) as exc:
            return f"The tool couldn't use that input or read the response ({exc.__class__.__name__}).", True

    def _run(self, name: str, a: dict) -> str:
        if name == "internal_records":
            return internal_evidence.records(self.registry, list(a.get("sheets") or []), self.asset_ids,
                                             a.get("incident_type"), fetch=self.internal_fetch)
        if name == "library_lookup":
            return internal_evidence.library(self.registry, str(a["query"]), search=self.library_search)
        if name == "attack_techniques":
            return attack.search(self.outbound, self.registry, str(a["keywords"]), index=self.attack_index)
        if name == "nvd_search":
            return nvd.search(self.outbound, self.registry, str(a["keyword"]))
        if name == "kev_check":
            return kev.check(self.outbound, self.registry, list(a["cve_ids"]))
        if name == "epss_scores":
            return epss.scores(self.outbound, self.registry, list(a["cve_ids"]))
        if name == "web_search":
            return web.search(self.outbound, self.registry, self.client, self.model, str(a["query"]),
                              self.allowed_domains)
        if name == "web_fetch":
            return web.fetch(self.outbound, self.registry, str(a["url"]), keep_text=self.mode == "library")
        raise KeyError(name)
