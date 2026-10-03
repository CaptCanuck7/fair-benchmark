import csv
import io

from conftest import load_fixture


def create(client, doc=None) -> dict:
    r = client.post("/api/analyses", json=doc) if doc is not None else client.post("/api/analyses")
    assert r.status_code == 201, r.text
    return r.json()


def product_x_doc(iterations=10_000) -> dict:
    doc = load_fixture("product_x.json")
    doc["settings"]["iterations"] = iterations
    return doc


# ---------------------------------------------------------------- basics

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_factor_content(client):
    body = client.get("/api/content/factors").json()
    assert body["factors"]["tef"]["label"] == "Threat event frequency"
    assert body["factors"]["secondary.fines"]["kind"] == "money"
    assert [f["key"] for f in body["forms"]["primary"]] == ["productivity", "response", "replacement"]
    assert body["confidence"]["high"]["lam"] == 6


def test_create_blank(client):
    doc = create(client)
    assert doc["format"] == "fair-workbench" and doc["title"] == "Untitled analysis"
    assert len(doc["states"]) == 1 and doc["states"][0]["name"] == "Current state"
    assert doc["states"][0]["lef"]["vulnMode"] == "direct"
    assert doc["settings"] == {"iterations": 10000, "seed": 20260930, "threshold": None}


def test_crud_round_trip(client):
    doc = create(client)
    aid = doc["id"]

    doc["title"] = "Renamed"
    doc["scope"]["asset"] = "Customer database"
    r = client.put(f"/api/analyses/{aid}", json=doc)
    assert r.status_code == 200
    assert r.json()["updatedAt"] >= doc["updatedAt"]
    assert r.headers["X-Input-Hash"]

    got = client.get(f"/api/analyses/{aid}").json()
    assert got["title"] == "Renamed" and got["scope"]["asset"] == "Customer database"

    listing = client.get("/api/analyses").json()
    assert [a["id"] for a in listing] == [aid]
    assert listing[0]["title"] == "Renamed" and listing[0]["states"] == 1 and listing[0]["latestRun"] is None

    dup = client.post(f"/api/analyses/{aid}/duplicate")
    assert dup.status_code == 201
    assert dup.json()["id"] != aid and dup.json()["title"] == "Renamed (copy)"
    assert len(client.get("/api/analyses").json()) == 2

    assert client.delete(f"/api/analyses/{aid}").status_code == 204
    assert client.get(f"/api/analyses/{aid}").status_code == 404
    assert len(client.get("/api/analyses").json()) == 1


def test_put_keeps_path_id_and_created_at(client):
    doc = create(client)
    sent = dict(doc, id="something-else", createdAt="1999-01-01T00:00:00Z")
    back = client.put(f"/api/analyses/{doc['id']}", json=sent).json()
    assert back["id"] == doc["id"] and back["createdAt"] == doc["createdAt"]


def test_missing_analysis_is_404(client):
    assert client.get("/api/analyses/nope").status_code == 404
    assert client.put("/api/analyses/nope", json={}).status_code == 404
    assert client.post("/api/analyses/nope/runs").status_code == 404
    assert client.get("/api/analyses/nope/runs/x").status_code == 404


# ---------------------------------------------------------------- runs

def test_run_list_fetch_and_stale_hash(client):
    doc = create(client, product_x_doc())
    aid = doc["id"]
    hash_before = client.get(f"/api/analyses/{aid}").headers["X-Input-Hash"]

    r = client.post(f"/api/analyses/{aid}/runs")
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["inputHash"] == hash_before
    assert run["iterations"] == 10_000 and run["seed"] == 20260930
    state = run["results"]["states"][0]
    assert 200_000 < state["meanAnnualLoss"] < 290_000
    assert len(state["exceedanceCurve"]) == 121 and len(state["histogram"]["bins"]) == 24
    assert run["documentSnapshot"]["states"][0]["lef"]["tef"]["ml"] == 2

    runs = client.get(f"/api/analyses/{aid}/runs").json()
    assert [x["id"] for x in runs] == [run["id"]]
    assert runs[0]["options"][0]["meanAnnualLoss"] == state["meanAnnualLoss"]
    assert "results" not in runs[0]

    full = client.get(f"/api/analyses/{aid}/runs/{run['id']}").json()
    assert full["results"] == run["results"]

    listing = client.get("/api/analyses").json()[0]
    assert listing["latestRun"]["options"][0]["meanAnnualLoss"] == state["meanAnnualLoss"]
    assert listing["latestRun"]["stale"] is False

    # Renaming and notes don't change the hash; inputs do.
    doc["title"] = "New title"
    doc["states"][0]["name"] = "Baseline"
    doc["states"][0]["notes"] = "note"
    doc["scope"]["notes"] = "note"
    assert client.put(f"/api/analyses/{aid}", json=doc).headers["X-Input-Hash"] == hash_before
    doc["states"][0]["lef"]["tef"]["max"] = 7
    assert client.put(f"/api/analyses/{aid}", json=doc).headers["X-Input-Hash"] != hash_before
    assert client.get("/api/analyses").json()[0]["latestRun"]["stale"] is True


def test_run_on_invalid_document_lists_failing_paths(client):
    doc = create(client)
    r = client.post(f"/api/analyses/{doc['id']}/runs")
    assert r.status_code == 422
    body = r.json()
    assert body["detail"] == "Fix Current state: Threat event frequency: Enter a range for threat event frequency."
    paths = [e["path"] for e in body["errors"]]
    assert paths[:2] == ["states[0].lef.tef", "states[0].lef.vuln"]
    assert client.get(f"/api/analyses/{doc['id']}/runs").json() == []


def test_run_with_implausible_frequency(client):
    doc = load_fixture("product_x.json")
    doc["settings"]["iterations"] = 100_000
    doc["states"][0]["lef"]["tef"] = {"min": 5000, "ml": 5000, "max": 5000, "conf": "med", "src": "x"}
    doc["states"][0]["lef"]["vuln"] = {"min": 100, "ml": 100, "max": 100, "conf": "med", "src": "x"}
    r = client.post("/api/simulate", json=doc)
    assert r.status_code == 422 and "implausible" in r.json()["detail"]


def test_validate(client):
    doc = product_x_doc()
    body = client.post("/api/validate", json=doc).json()
    assert body["valid"] is True and body["states"][0]["checks"] == []

    doc["states"][0]["lef"]["vuln"]["max"] = 150
    body = client.post("/api/validate", json=doc).json()
    assert body["valid"] is False
    assert body["states"][0]["checks"][0]["path"] == "states[0].lef.vuln"
    assert body["states"][0]["checks"][0]["message"] == "Vulnerability: Use values between 0 and 100."


def test_stateless_simulate_matches_stored_run(client):
    doc = product_x_doc()
    stateless = client.post("/api/simulate", json=doc).json()
    aid = create(client, doc)["id"]
    stored = client.post(f"/api/analyses/{aid}/runs").json()
    assert stateless["states"][0]["meanAnnualLoss"] == stored["results"]["states"][0]["meanAnnualLoss"]
    assert stateless["inputHash"] == stored["inputHash"]


# ---------------------------------------------------------------- validation and limits

def test_invalid_document_gives_422_with_paths(client):
    doc = product_x_doc()
    doc["states"][0]["lef"]["mode"] = "guess"
    doc["states"][0]["primary"]["response"]["min"] = "lots"
    r = client.post("/api/simulate", json=doc)
    assert r.status_code == 422
    paths = {e["path"] for e in r.json()["errors"]}
    assert {"states[0].lef.mode", "states[0].primary.response.min"} <= paths


def test_iterations_above_limit_rejected(client):
    doc = product_x_doc(iterations=200_001)
    for r in (client.post("/api/simulate", json=doc), client.post("/api/analyses", json=doc)):
        assert r.status_code == 422
        assert r.json()["errors"][0]["path"] == "settings.iterations"
    aid = create(client)["id"]
    blank = client.get(f"/api/analyses/{aid}").json()
    blank["settings"]["iterations"] = 1_000_000
    assert client.put(f"/api/analyses/{aid}", json=blank).status_code == 422


def test_body_size_limit(client):
    doc = product_x_doc()
    doc["scope"]["notes"] = "x" * (1024 * 1024)
    r = client.post("/api/simulate", json=doc)
    assert r.status_code == 413

    def chunks():  # no Content-Length
        yield b'{"scope":{"notes":"'
        for _ in range(20):
            yield b"x" * 65536
        yield b'"}}'

    r = client.post("/api/import", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ---------------------------------------------------------------- import and export

def test_import_prototype_export(client):
    raw = load_fixture("prototype_export.json")
    r = client.post("/api/import", json=raw)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["id"] != raw["id"]
    assert doc["summary"] is None
    assert doc["title"] == "Payments API outage" and doc["active"] == 1
    assert [s["name"] for s in doc["states"]] == ["Current state", "Multi-region failover"]
    assert doc["states"][0]["lef"]["cf"] == raw["states"][0]["lef"]["cf"]
    assert doc["states"][1]["cost"] == 60000

    run = client.post(f"/api/analyses/{doc['id']}/runs")
    assert run.status_code == 201, run.text
    res = run.json()["results"]
    assert res["states"][0]["derivedVulnerability"] is not None
    assert res["comparison"]["rows"][1]["reduction"] > 0


def test_import_fills_missing_fields(client):
    raw = {"title": "Old export", "states": [{"lef": {"mode": "lef", "lef": {"min": 0.1, "ml": 0.2, "max": 0.5}}},
                                             {"name": None, "secondary": None}]}
    doc = client.post("/api/import", json=raw).json()
    s0, s1 = doc["states"]
    assert s0["name"] == "Current state" and s1["name"] == "Treatment option 1"
    assert s0["id"] and s1["id"] and s0["id"] != s1["id"]
    assert s0["lef"]["lef"] == {"min": 0.1, "ml": 0.2, "max": 0.5, "conf": "med", "src": ""}
    assert s0["lef"]["vulnMode"] == "direct"
    assert s1["secondary"]["fines"] == {"min": None, "ml": None, "max": None, "conf": "med", "src": ""}
    assert doc["settings"]["seed"] == 20260930 and doc["scope"]["threatType"] == "Malicious, external"


def test_import_rejects_documents_without_states(client):
    for body in ({"title": "x"}, {"states": "nope"}, [1, 2]):
        r = client.post("/api/import", json=body)
        assert r.status_code == 422
        assert "states" in r.json()["detail"] or "JSON object" in r.json()["detail"]


def test_export_import_round_trip(client):
    raw = load_fixture("prototype_export.json")
    raw["settings"]["iterations"] = 1_000
    aid = client.post("/api/import", json=raw).json()["id"]

    # Before any run: summary present but empty, as the prototype writes it.
    exp = client.get(f"/api/analyses/{aid}/export.json")
    assert exp.status_code == 200
    assert exp.headers["content-disposition"] == 'attachment; filename="payments-api-outage.json"'
    assert exp.json()["summary"]["options"] == [] and exp.json()["summary"]["stale"] is False

    run = client.post(f"/api/analyses/{aid}/runs").json()
    exported = client.get(f"/api/analyses/{aid}/export.json").json()
    s = exported["summary"]
    assert s["runAt"] == run["runAt"] and s["stale"] is False and s["threshold"] == 500000
    assert [o["name"] for o in s["options"]] == ["Current state", "Multi-region failover"]
    o = s["options"][0]
    assert isinstance(o["meanAnnualLoss"], int) and o["meanAnnualLoss"] == round(run["results"]["states"][0]["meanAnnualLoss"])
    assert set(o) >= {"annualCost", "p10", "p99", "chanceAboveThreshold", "lefP10", "singleLossMean", "breakdown"}

    again = client.post("/api/import", json=exported)
    assert again.status_code == 201
    doc2 = again.json()
    assert doc2["id"] not in (aid, exported["id"])
    assert doc2["states"] == exported["states"] and doc2["settings"] == exported["settings"]
    run2 = client.post(f"/api/analyses/{doc2['id']}/runs").json()
    assert run2["inputHash"] == run["inputHash"]
    assert run2["results"]["states"][0]["meanAnnualLoss"] == run["results"]["states"][0]["meanAnnualLoss"]


def test_export_csv(client):
    raw = load_fixture("prototype_export.json")
    raw["settings"]["iterations"] = 1_000
    aid = client.post("/api/import", json=raw).json()["id"]
    run = client.post(f"/api/analyses/{aid}/runs").json()

    r = client.get(f"/api/analyses/{aid}/runs/{run['id']}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="payments-api-outage-results.csv"'
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["Option", "Annual cost", "Mean annual loss", "P10", "P50", "P90", "P95", "P99",
                       "Chance of any loss", "Chance above threshold", "LEF mean", "Single loss P50", "Single loss P90"]
    assert rows[1][0] == "Current state" and rows[1][1] == ""
    assert rows[2][0] == "Multi-region failover" and rows[2][1] == "60000"
    assert rows[1][2] == str(round(run["results"]["states"][0]["meanAnnualLoss"]))
    assert 0 < float(rows[1][9]) < 1
    assert client.get(f"/api/analyses/{aid}/runs/nope/export.csv").status_code == 404


def test_delete_removes_runs(client):
    aid = create(client, product_x_doc(iterations=1_000))["id"]
    run_id = client.post(f"/api/analyses/{aid}/runs").json()["id"]
    client.delete(f"/api/analyses/{aid}")
    from app.db import SessionLocal
    from app.models import RunRow

    with SessionLocal() as s:
        assert s.get(RunRow, run_id) is None
