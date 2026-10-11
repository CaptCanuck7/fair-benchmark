"""Task 5: evidence gathering (section 9.5). A bounded tool-use loop: at most
12 tool calls and 120 seconds per risk, then the model must answer.

After the loop, plain code checks the answer:
- An item whose citation no tool returned in this run is rejected and listed.
- Origin, source type, source name and publication date come from what the
  tool returned, not from the model; items over 24 months old are flagged stale.
- Each factor group (frequency, susceptibility, primary loss, secondary loss)
  must end with evidence or a data request. A group with neither gets a
  plain-language request, marked as added automatically.
"""

import json

from pydantic import BaseModel

from app.llm import LLM, LLMResult, untrusted
from app.numbers import value_in_record
from app.schemas import FACTOR_GROUPS, NON_MALICIOUS, EvidenceOutput, EvidenceRequest
from app.tasks.common import load_prompt, render_risk
from app.tools.base import Registry, is_stale
from app.tools.toolbox import Toolbox

PROMPT_VERSION = "evidence.v2"
MAX_TOOL_CALLS = 12
MAX_SECONDS = 120.0

# Section 7's routing table: where to look first, by condition type.
ROUTES = {
    "unsupported_software": "findings, NVD, the CISA exploited-vulnerabilities catalog, EPSS, vendor advisories, "
                            "security telemetry",
    "missing_control": "control tests and assessments, MITRE ATT&CK, the reference library, incident history",
    "misconfiguration": "findings, CIS Benchmarks (cisecurity.org), control tests and assessments",
    "process_gap": "control tests and assessments, incident history, the reference library",
    "third_party": "vendor assessments, incident history, public breach disclosures",
    "other": "incident history, telemetry, control tests and the reference library",
}

# Lookups the loop requires when they're offered (AGENT_FIXES.md fix 7), and why.
REQUIRED_WHY = {
    "library_lookup": "the reference library holds approved industry figures (breach frequency, cost per record) "
                      "that any risk can use",
    "nvd_search": "the technology involved may have published vulnerabilities; search by its generic product or "
                  "protocol name",
    "web_search": "third-party and unsupported-software risks need public security research and disclosed "
                  "incidents about the kind of technology involved, searched in generic terms",
}
WEB_SEARCH_TYPES = {"third_party", "unsupported_software"}
# Every evidence tool, in the order coverage lists them.
EVIDENCE_TOOLS = ("internal_records", "library_lookup", "attack_techniques", "nvd_search", "kev_check",
                  "epss_scores", "web_search", "web_fetch")
CVE_TOOLS = {"nvd_search", "kev_check", "epss_scores"}


def required_tools(req: EvidenceRequest, toolbox: Toolbox) -> dict[str, str]:
    """The lookups this run must make: the library always; NVD whenever it is
    offered (external sources on, malicious threat); web search when offered
    for a malicious threat whose condition type is third party or unsupported
    software."""
    c = req.classification
    types = {c.primary_type, c.secondary_type} if c else set()
    malicious = req.scenario.get("threat_type", "") not in NON_MALICIOUS
    needed = ["library_lookup", "nvd_search"]
    if malicious and types & WEB_SEARCH_TYPES:
        needed.append("web_search")
    return {t: REQUIRED_WHY[t] for t in needed if t in toolbox.names}


def coverage(toolbox: Toolbox, required: dict[str, str], items: list[dict], budget_spent: bool) -> dict:
    """What each source did in this run, for the Evidence tab. A blocked or
    failed call is an attempt, not a check. `reason` says why a source with no
    checks wasn't checked: external_off, threat_type, blocked, failed, budget,
    or not_called (required, budget left, still not called)."""
    found: dict[str, int] = {}
    for i in items:
        tool = toolbox.tool_of.get(i["citation"])
        if tool:
            found[tool] = found.get(tool, 0) + 1
    tools = {}
    for name in EVIDENCE_TOOLS:
        s = toolbox.stats.get(name, {"calls": 0, "blocked": 0, "failed": 0})
        offered = name in toolbox.names
        checks = s["calls"] - s["blocked"] - s["failed"]
        reason = None
        if not offered:
            reason = "external_off" if not toolbox.external else "threat_type" if name in CVE_TOOLS else None
        elif checks == 0:
            if s["blocked"]:
                reason = "blocked"
            elif s["failed"]:
                reason = "failed"
            elif budget_spent:
                reason = "budget"
            elif name in required:
                reason = "not_called"
        tools[name] = {"offered": offered, "required": name in required, **s, "checks": checks,
                       "items": found.get(name, 0), "reason": reason}
    return {"tools": tools, "budgetSpent": budget_spent}


# Requests added when the model leaves a group uncovered.
BACKSTOP = {
    "frequency": ("SOC", "tef",
                  "In the last 12 months, how many times were these systems targeted by the kind of event this risk "
                  "describes, counting blocked attempts, alerts and incidents?"),
    "susceptibility": ("Vulnerability Management", "vuln",
                       "Do recent penetration tests, control tests or scans show whether these systems would stop the "
                       "attacks or failures this risk describes? Please share the results and dates."),
    "primary": ("Finance", "primary.response",
                "What did similar past incidents cost to respond to and recover from, counting staff hours, outside "
                "help and lost revenue?"),
    "secondary": ("Legal", "secondary.response",
                  "If the data on these systems were exposed or the service failed, how many customers or people "
                  "would need to be notified, and what fines, penalties or contract credits could apply?"),
}


class EvidenceResult(BaseModel):
    items: list[dict]
    data_requests: list[dict]
    rejected: list[dict]
    tool_calls: int
    notes: dict


def group_of(factor: str) -> str | None:
    return next((g for g, keys in FACTOR_GROUPS.items() if factor in keys), None)


def _vectors_text(vectors: dict | None) -> str:
    if not vectors:
        return "No approved attack vectors or failure paths yet."
    lines = []
    for p in vectors.get("paths", []):
        lines.append(f"- {p['title']}: " + " / ".join(s["text"] for s in p.get("steps", [])))
    return "\n".join(lines)


def build_user(req: EvidenceRequest, toolbox: Toolbox, required: dict[str, str] | None = None) -> str:
    c = req.classification
    routing = []
    if c:
        for t in [c.primary_type] + ([c.secondary_type] if c.secondary_type else []):
            routing.append(f"- {t}: {ROUTES.get(t, ROUTES['other'])}")
    threat = req.scenario.get("threat_type", "")
    notes = []
    if "nvd_search" not in toolbox.names:
        notes.append("No CVE lookups are available for this task" +
                     (" because the threat type is not malicious." if threat in NON_MALICIOUS else "."))
    if "web_search" not in toolbox.names:
        notes.append("External sources are turned off: use internal records and the reference library only.")
    return (
        f"{render_risk(req.risk)}\n\n"
        f"{untrusted('scenario', json.dumps(req.scenario, indent=1, ensure_ascii=False))}\n\n"
        f"Approved attack vectors or failure paths:\n{_vectors_text(req.vectors)}\n\n"
        "Sources to try first for this condition type:\n" + ("\n".join(routing) or "- incident history, telemetry, "
                                                             "control tests") + "\n\n"
        "Required lookups for this run (make them early; they count toward the budget):\n"
        + ("\n".join(f"- {t}: {why}" for t, why in (required or {}).items()) or "- none") + "\n\n"
        "Factor groups that each need evidence or a data request: frequency (tef, lef, cf, poa), susceptibility "
        "(vuln, tcap, rs), primary loss (primary.*), secondary loss (slef, secondary.*).\n"
        f"Tool budget: {MAX_TOOL_CALLS} calls and {int(MAX_SECONDS)} seconds. "
        + " ".join(notes) +
        "\nGather the evidence, then return the JSON."
    )


def value_check(value: float | None, fields: dict | None) -> str:
    """found or not_found when the value can be compared with its source
    record; not_checked with no value or no record (web results, feeds). A
    value not found may be derived (hours x rate), so the item is kept."""
    if value is None or not fields:
        return "not_checked"
    return "found" if value_in_record(value, fields) else "not_found"


def postprocess(out: EvidenceOutput, registry: Registry, toolbox: Toolbox, tool_calls: int,
                threat_type: str, required: dict[str, str] | None = None,
                budget_spent: bool = False) -> EvidenceResult:
    items, rejected, seen = [], [], set()
    for item in out.items:
        src = registry.get(item.citation)
        if src is None:
            rejected.append({"citation": item.citation, "summary": item.summary,
                             "reason": "No tool returned this citation in this run."})
            continue
        key = (src.citation, tuple(sorted(item.factors)), item.summary)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "origin": src.origin, "source_type": src.source_type, "source_name": src.source_name,
            "citation": src.citation, "published_at": src.published_at, "retrieved_at": src.retrieved_at,
            "summary": item.summary, "value": item.value, "unit": item.unit, "factors": list(item.factors),
            "stale": is_stale(src.published_at),
            "value_check": value_check(item.value, src.fields),
            "source_fields": src.fields,
        })

    requests = [r.model_dump() for r in out.data_requests]
    covered = {group_of(f) for i in items for f in i["factors"]} | {group_of(r["factor"]) for r in requests}
    backstopped = []
    for group, (team, factor, question) in BACKSTOP.items():
        if group not in covered:
            backstopped.append(group)
            requests.append({"team": team, "factor": factor, "question": question,
                             "reason": "No evidence was found for this part of the risk. Added automatically "
                                       "because the agent didn't raise a request for it."})
    return EvidenceResult(items=items, data_requests=requests, rejected=rejected, tool_calls=tool_calls, notes={
        "toolsOffered": toolbox.names,
        "cveLookupsOffered": "nvd_search" in toolbox.names,
        "cveLookupsMade": registry.cve_lookups,
        "threatType": threat_type,
        "backstopGroups": backstopped,
        "coverage": coverage(toolbox, required or {}, items, budget_spent),
    })


def run(llm: LLM, req: EvidenceRequest, toolbox: Toolbox) -> LLMResult[EvidenceResult]:
    required = required_tools(req, toolbox)
    res = llm.tool_loop(
        load_prompt(PROMPT_VERSION), build_user(req, toolbox, required), EvidenceOutput, toolbox.definitions(),
        toolbox.execute, max_calls=MAX_TOOL_CALLS, max_seconds=MAX_SECONDS, effort="medium",
        required_tools=required,
    )
    result = postprocess(res.output, toolbox.registry, toolbox, res.tool_calls, req.scenario.get("threat_type", ""),
                         required, res.budget_spent)
    return LLMResult(output=result, usage=res.usage, attempts=res.attempts, tool_calls=res.tool_calls)
