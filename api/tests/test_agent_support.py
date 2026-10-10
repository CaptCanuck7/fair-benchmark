from conftest import AGENT_DATA, REAL_FETCH_AGENT_STATUS

from app.identifiers import person_variants
from app.config import settings
from app.routers import agent as agent_router

REGISTER = AGENT_DATA / "tactical_risk_register_test.xlsx"


def import_register(client):
    res = client.post("/api/register/import",
                      files={"file": ("r.xlsx", REGISTER.read_bytes(), "application/octet-stream")})
    assert res.status_code == 201


def test_person_variants_strip_titles_and_add_surname():
    assert person_variants("VP Ben Nakamura") == ["VP Ben Nakamura", "Ben Nakamura", "Nakamura"]
    assert person_variants("Morgan Lee") == ["Morgan Lee", "Lee"]


def test_identifiers_cover_every_class(client):
    import_register(client)
    ids = client.get("/internal/guard/identifiers").json()
    by_kind: dict[str, set] = {}
    for i in ids:
        by_kind.setdefault(i["kind"], set()).add(i["value"])
    assert {"TR-6", "TR-18", "Monitoring Task-5"} <= by_kind["risk_id"]
    assert {"VUL-20417", "IAM-48211"} <= by_kind["ticket_id"]
    assert {"Asset-412", "Asset-377"} <= by_kind["asset_id"]
    assert "INC-2026-021" in by_kind["incident_id"]
    assert "FND-1041" in by_kind["finding_id"]
    assert {"CT-311", "PT-058"} <= by_kind["record_id"]
    assert {"Sarah Chen", "VP Ben Nakamura", "Ben Nakamura", "Nakamura", "Morgan Lee"} <= by_kind["person"]
    assert {"Product", "Emerging Tech", "Workplace Services"} <= by_kind["business_unit"]
    assert {"Excelsior", "Nova", "Granite", "Osgiliath"} <= by_kind["environment"]
    assert "Customer SFTP server 1" in by_kind["asset_name"]
    # Non-asset areas in the evidence ("Organization-wide", "Corporate email") are not identifiers.
    assert "Organization-wide" not in by_kind["asset_id"]


def test_outbound_log_round_trip(client):
    entry = {"agent_run_id": "run-1", "tool": "nvd", "destination": "https://services.nvd.nist.gov/rest/json/cves/2.0",
             "query": "openssh", "allowed": True, "blocked_reason": None}
    assert client.post("/internal/outbound-log", json=entry).status_code == 201
    blocked = {**entry, "query": "[asset_id] exploit", "allowed": False, "blocked_reason": "identifier:asset_id"}
    assert client.post("/internal/outbound-log", json=blocked).status_code == 201
    log = client.get("/api/agent/outbound-log").json()
    assert [e["allowed"] for e in log] == [False, True]  # newest first
    assert log[0]["blockedReason"] == "identifier:asset_id" and log[0]["agentRunId"] == "run-1"


def test_outbound_log_rejects_bad_entries(client):
    assert client.post("/internal/outbound-log", json={"tool": "nvd"}).status_code == 422


def test_status_when_agent_is_unreachable(client, monkeypatch):
    monkeypatch.setattr(agent_router, "fetch_agent_status", REAL_FETCH_AGENT_STATUS)
    monkeypatch.setattr(settings, "agent_url", "http://127.0.0.1:9")
    status = client.get("/api/agent/status").json()
    assert status["configured"] is False
    assert "isn’t running" in status["reason"]
