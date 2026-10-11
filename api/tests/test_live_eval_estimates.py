"""Live evaluation of first-pass estimates (AGENT_BUILD.md sections 9.6 and 14).

Opt in: `docker compose exec api pytest -m live -s tests/test_live_eval_estimates.py`.
Intake, scenarios and evidence are replayed from the recorded fixtures;
estimates call the real agent and the Claude API for the 9 qualifying risks.
Everything uses a throwaway in-memory database.

Set RECORD_DIR to save the outputs as estimates_recorded.json.
"""

import copy
import json
import os
import re
from pathlib import Path

import pytest
from conftest import FIXTURES
from test_live_eval import REGISTER
from test_live_eval_scenarios import QUALIFYING

from app import agent_client, agent_pipeline
from app.agent_client import TaskResult, fetch_agent_status

pytestmark = pytest.mark.live

RECORDED = {}
for name in ("intake_recorded.json", "scenario_recorded.json", "evidence_recorded.json"):
    RECORDED.update(json.loads((FIXTURES / name).read_text(encoding="utf-8")))

# Section 14, TR-7: the rationale notes that zero confirmed logins is weak evidence.
ZERO = re.compile(r"\b(zero|no|0)\s+(confirmed|successful|observed|known)\b[^.]{0,40}"
                  r"(login|log-in|sign-in|credential|compromise|event|incident|loss)", re.IGNORECASE)
WEAK = re.compile(r"weak|absence|not (the same as|evidence)|doesn.t (mean|show|prove)|does not (mean|show|prove)|"
                  r"undercount|detection|unobserved|undetected", re.IGNORECASE)


def zero_logins_is_weak(text: str) -> bool:
    return bool(ZERO.search(text) and WEAK.search(text))


def estimate_problems(rid: str, out: dict, evidence: dict[int, dict], required: list[tuple[str, ...]]) -> list[str]:
    """The rules every estimates output must meet, checked from the API's side."""
    problems = []
    kinds = {"pct": 100, "score": 100}
    from app.content.factors import F
    covered = set()
    for e in out["estimates"]:
        f = e["factor"]
        covered.add(f)
        if not e["evidence_ids"]:
            problems.append(f"{rid} {f}: a range without evidence")
        missing = [i for i in e["evidence_ids"] if i not in evidence]
        if missing:
            problems.append(f"{rid} {f}: cites unknown evidence {missing}")
        if not (0 <= e["min"] <= e["ml"] <= e["max"]):
            problems.append(f"{rid} {f}: range out of order {e['min']}/{e['ml']}/{e['max']}")
        cap = kinds.get(F[f]["kind"])
        if cap and e["max"] > cap:
            problems.append(f"{rid} {f}: above 100")
        cited = [evidence[i] for i in e["evidence_ids"] if i in evidence]
        if cited and all(c["origin"] == "external" for c in cited) and e["conf"] != "low":
            problems.append(f"{rid} {f}: external evidence only but confidence {e['conf']}")
    for u in out["unestimated"]:
        covered.add(u["factor"])
        if (u.get("data_request_id") is None) == (u.get("new_request") is None):
            problems.append(f"{rid} {u['factor']}: unestimated needs exactly one data request")
    gaps = [" or ".join(group) for group in required if not covered & set(group)]
    if gaps:
        problems.append(f"{rid}: required factors not covered: {gaps}")
    return problems


def required_for(method: dict) -> list[tuple[str, ...]]:
    """As the agent's schema: each tuple is satisfied by any one of its factors."""
    vuln = [("vuln",)] if method["vuln_mode"] == "direct" else [("tcap",), ("rs",)]
    freq = {"lef": [("lef",)], "tef_vuln": [("tef",), *vuln], "cf_poa": [("cf",), ("poa",), *vuln]}[method["mode"]]
    return [*freq, ("primary.productivity", "primary.response", "primary.replacement"), ("slef",),
            ("secondary.fines", "secondary.competitive", "secondary.reputation")]


def test_estimates_on_qualifying_risks(client, monkeypatch):
    status = fetch_agent_status()
    if not status["configured"]:
        pytest.skip(f"Agent not configured: {status['reason']}")
    recorded: dict[str, dict] = {"estimates": {}}
    real_call = agent_client.call_task

    def call(task, payload):
        title = (payload.get("risk") or {}).get("title")
        if task in ("quality", "triage", "classify", "scenario", "evidence"):
            return TaskResult(output=RECORDED[task][title], model="recorded", prompt_version=f"{task}.v1",
                              input_tokens=0, output_tokens=0)
        res = real_call(task, payload)
        recorded[task][title] = copy.deepcopy(res.output)
        return res

    monkeypatch.setattr(agent_pipeline, "submit", lambda fn, risk_pk, *a: fn(risk_pk, *a))
    monkeypatch.setattr(agent_client, "call_task", call)
    client.post("/api/register/import", files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})

    problems, rows = [], []
    tokens = [0, 0]
    for rid in QUALIFYING:
        client.post(f"/api/agent/risks/{rid}/scenario")
        sid = client.get(f"/api/register/risks/{rid}").json()["scenario"]["id"]
        client.put(f"/api/drafts/{sid}", json={"action": "approve"})
        client.post(f"/api/agent/risks/{rid}/evidence")
        res = client.post(f"/api/agent/risks/{rid}/estimates")
        if res.status_code != 202:
            problems.append(f"{rid}: estimates didn't start: {res.json().get('detail')}")
            continue
        d = client.get(f"/api/register/risks/{rid}").json()
        run = next(r for r in d["runs"] if r["task"] == "estimates")
        tokens[0] += run["inputTokens"]
        tokens[1] += run["outputTokens"]
        if run["status"] != "succeeded":
            problems.append(f"{rid}: estimates run {run['status']}: {run['error']}")
            continue
        out = recorded["estimates"][d["title"]]
        evidence = {e["id"]: e for e in d["evidence"]}
        problems += estimate_problems(rid, out, evidence, required_for(out["method"]))
        # The anchoring guard: no agent range leaves the API before a reveal.
        if any(f["agent"] is not None for f in d["estimates"]["factors"]):
            problems.append(f"{rid}: an agent range is visible before reveal")
        m = out["method"]
        rows.append(f"{rid:6} {m['mode']:8} {m['vuln_mode']:7} {len(out['estimates']):2} ranges "
                    f"{len(out['unestimated']):2} unestimated  "
                    + " ".join(f"{e['factor']}={e['conf']}" for e in out["estimates"][:3]))
        if rid == "TR-7":
            text = " ".join(e["rationale"] for e in out["estimates"]) + " " + m["reason"]
            if not zero_logins_is_weak(text):
                problems.append("TR-7: no rationale notes that zero confirmed logins is weak evidence")

    print("\nRisk   Method   Vuln")
    print("\n".join(rows))
    print(f"Tokens (estimates): {tokens[0]:,} in, {tokens[1]:,} out.")
    if os.environ.get("RECORD_DIR"):
        out_path = Path(os.environ["RECORD_DIR"]) / "estimates_recorded.json"
        out_path.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded model outputs to {out_path}")
    assert not problems, "\n".join(problems)
