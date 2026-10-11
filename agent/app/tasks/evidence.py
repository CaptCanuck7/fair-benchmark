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
from app.schemas import FACTOR_GROUPS, NON_MALICIOUS, EvidenceOutput, EvidenceRequest
from app.tasks.common import load_prompt, render_risk
from app.tools.base import Registry, is_stale
from app.tools.toolbox import Toolbox

PROMPT_VERSION = "evidence.v1"
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


def build_user(req: EvidenceRequest, toolbox: Toolbox) -> str:
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
        "Factor groups that each need evidence or a data request: frequency (tef, lef, cf, poa), susceptibility "
        "(vuln, tcap, rs), primary loss (primary.*), secondary loss (slef, secondary.*).\n"
        f"Tool budget: {MAX_TOOL_CALLS} calls and {int(MAX_SECONDS)} seconds. "
        + " ".join(notes) +
        "\nGather the evidence, then return the JSON."
    )


def postprocess(out: EvidenceOutput, registry: Registry, toolbox: Toolbox, tool_calls: int,
                threat_type: str) -> EvidenceResult:
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
    })


def run(llm: LLM, req: EvidenceRequest, toolbox: Toolbox) -> LLMResult[EvidenceResult]:
    res = llm.tool_loop(
        load_prompt(PROMPT_VERSION), build_user(req, toolbox), EvidenceOutput, toolbox.definitions(),
        toolbox.execute, max_calls=MAX_TOOL_CALLS, max_seconds=MAX_SECONDS, effort="medium",
    )
    result = postprocess(res.output, toolbox.registry, toolbox, res.tool_calls, req.scenario.get("threat_type", ""))
    return LLMResult(output=result, usage=res.usage, attempts=res.attempts, tool_calls=res.tool_calls)
