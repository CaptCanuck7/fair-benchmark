"""Live evaluation of evidence gathering (AGENT_BUILD.md section 14).

Opt in: `docker compose exec api pytest -m live -s tests/test_live_eval_evidence.py`.
Intake and scenarios are replayed from the recorded fixtures; evidence
gathering calls the real agent, the Claude API and the allowlisted public
sources for the 9 qualifying risks, so it spends tokens and web searches and
takes several minutes.

The agent reads identifiers, internal evidence and the reference library from
the running api, and writes its outbound log there: this run's requests appear
on the Settings page. Everything else uses a throwaway in-memory database.

Set RECORD_DIR to save the outputs as evidence_recorded.json.
"""

import json
import os
import re
from pathlib import Path

import httpx
import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER
from test_live_eval_scenarios import QUALIFYING

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult, fetch_agent_status
from app.db import SessionLocal
from app.evidence import SHEETS
from app.identifiers import build_identifiers

pytestmark = pytest.mark.live

RECORDED = {**json.loads((FIXTURES / "intake_recorded.json").read_text(encoding="utf-8")),
            **json.loads((FIXTURES / "scenario_recorded.json").read_text(encoding="utf-8"))}
LIVE_API = "http://localhost:8000"  # the running api in this container, where the agent logs

# Section 14: records each risk's evidence should include (by citation fragment).
MUST_CITE = {
    "TR-6": ["INC-2026-021", "Findings FND-"],
    "TR-7": ["PT-058"],
    "TR-8": ["PT-064", "FND-1220"],
    "TR-9": ["CT-311", "INC-2024-077"],
    "TR-11": ["INC-2025-090", "CT-275"],
    "TR-12": ["INC-2025-046", "CT-340"],
    "TR-13": ["INC-2025-012", "FND-1302"],
}
CVE_TOOLS = {"nvd", "kev", "epss"}


def test_evidence_on_qualifying_risks(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")
    recorded: dict[str, dict] = {"evidence": {}}
    real_call = agent_client.call_task

    def call(task, payload):
        title = (payload.get("risk") or {}).get("title")
        if task in ("quality", "triage", "classify", "scenario"):
            return TaskResult(output=RECORDED[task][title], model="recorded", prompt_version=f"{task}.v1",
                              input_tokens=0, output_tokens=0)
        res = real_call(task, payload)
        recorded[task][title] = res.output
        return res

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})

    with SessionLocal() as s:
        internal_citations = {f"{sh.title} {r.record_id}" for sh in SHEETS for r in s.scalars(
            __import__("sqlalchemy").select(sh.model))}
        identifiers = [i["value"] for i in build_identifiers(s)]

    problems, rows, run_ids = [], [], {}
    tokens = [0, 0]
    for rid in QUALIFYING:
        client.post(f"/api/agent/risks/{rid}/scenario")
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        res = client.post(f"/api/agent/risks/{rid}/evidence")
        if res.status_code != 202:
            problems.append(f"{rid}: evidence didn't start: {res.json().get('detail')}")
            continue
        d = client.get(f"/api/register/risks/{rid}").json()
        run = next(r for r in d["runs"] if r["task"] == "evidence")
        tokens[0] += run["inputTokens"]
        tokens[1] += run["outputTokens"]
        if run["status"] != "succeeded":
            problems.append(f"{rid}: evidence run {run['status']}: {run['error']}")
            continue
        run_ids[rid] = run["id"]
        ev, reqs, er = d["evidence"], d["dataRequests"], d["evidenceRun"]
        cites = [e["citation"] for e in ev]
        rows.append(f"{rid:6} {len(ev):3} items {len(reqs):2} requests {er['toolCalls']:2} calls "
                    f"{len(er['rejected'])} rejected  backstop={er['notes'].get('backstopGroups')}  "
                    f"cve={er['notes'].get('cveLookupsMade')}")

        for frag in MUST_CITE.get(rid, []):
            if not any(frag in c for c in cites):
                problems.append(f"{rid}: no evidence citing {frag}")
        for e in ev:
            if e["origin"] == "internal" and not e["fromDataRequest"] and e["citation"] not in internal_citations:
                problems.append(f"{rid}: internal citation doesn't resolve: {e['citation']}")
            if e["origin"] == "external" and not e["citation"].startswith("https://"):
                problems.append(f"{rid}: external citation isn't a URL: {e['citation']}")
        covered = {g for e in ev for g in e["groups"]} | {g for r in reqs for g in r["groups"]}
        if covered != {"frequency", "susceptibility", "primary", "secondary"}:
            problems.append(f"{rid}: groups without evidence or a request: "
                            f"{sorted({'frequency', 'susceptibility', 'primary', 'secondary'} - covered)}")

        if rid == "TR-6" and not any(e["value"] == 410000 for e in ev):
            problems.append("TR-6: the 410,000 record count wasn't found")
        if rid == "TR-7" and not any("phish" in (e["summary"] + e["citation"]).lower() and
                                     e["sourceType"] == "telemetry" for e in ev):
            problems.append("TR-7: no phishing telemetry")
        if rid == "TR-9" and not any("frequency" in r["groups"] for r in reqs):
            problems.append("TR-9: no data request for frequency")
        if rid == "TR-11" and not any(r["team"] == "Asset Management" and "record" in r["question"].lower()
                                      for r in reqs):
            problems.append("TR-11: no data request to Asset Management for record counts")
        if rid == "TR-14" and not any("record" in r["question"].lower() for r in reqs):
            problems.append("TR-14: no data request for record counts")

    # The outbound log (in the running api): no CVE lookups for TR-12, no identifiers anywhere.
    log = httpx.get(f"{LIVE_API}/api/agent/outbound-log", params={"limit": 1000}, timeout=10).json()
    ours = [e for e in log if e["agentRunId"] in set(run_ids.values())]
    if run_ids.get("TR-12") and any(e["tool"] in CVE_TOOLS for e in ours if e["agentRunId"] == run_ids["TR-12"]):
        problems.append("TR-12: CVE lookups in the outbound log")
    pattern = re.compile("|".join(re.escape(i) for i in sorted(identifiers, key=len, reverse=True)
                                  if len(i) > 3), re.IGNORECASE)
    for e in ours:
        text = f"{e['destination']} {e['query'] or ''}"
        if pattern.search(text):
            problems.append(f"outbound log holds an identifier: {text[:120]}")
    blocked = [e for e in ours if not e["allowed"]]

    print("\nRisk   Evidence")
    print("\n".join(rows))
    print(f"Outbound requests: {len(ours)} ({len(blocked)} blocked: "
          f"{sorted({e['blockedReason'] for e in blocked})}).")
    print(f"Tokens (evidence): {tokens[0]:,} in, {tokens[1]:,} out.")
    if os.environ.get("RECORD_DIR"):
        out = Path(os.environ["RECORD_DIR"]) / "evidence_recorded.json"
        out.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded model outputs to {out}")
    assert not problems, "\n".join(problems)
