import io

import pytest
from conftest import AGENT_DATA
from openpyxl import Workbook

from app.register.parser import COLUMNS, RegisterError, parse_rows, parse_workbook
from app.register.sections import split_sections

REGISTER = AGENT_DATA / "tactical_risk_register_test.xlsx"
HEADER = [label for label, _ in COLUMNS]

ANALYSIS = (
    "Risk Statement: Attackers could steal data.\n\n"
    "Detailed Risk Analysis: The server is old.\n\n"
    "Baseline Controls: Firewall.\n\n"
    "Exploit Paths: (1) Remote exploit."
)


def row(risk_id="TR-1", **overrides) -> list:
    """A register row with the risk fields filled and no monitoring update."""
    values = {key: None for _, key in COLUMNS}
    values.update(risk_id=risk_id, risk_title="Old server", risk_analysis=ANALYSIS, assets="Asset-1, Asset-2",
                  baseline_impact=4, baseline_likelihood=3, baseline_risk_score=12,
                  target_residual_impact=2, target_residual_likelihood=2, target_residual_score=4)
    values.update(overrides)
    return [values[key] for _, key in COLUMNS]


def rows(*data_rows) -> list[tuple[int, list]]:
    return [(1, list(HEADER))] + [(i + 2, r) for i, r in enumerate(data_rows)]


def xlsx(*data_rows, header=HEADER) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in data_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- Parser ---


def test_test_register_gives_13_risks_from_14_rows():
    parsed = parse_workbook(REGISTER.read_bytes())
    assert parsed.row_count == 14
    assert len(parsed.risks) == 13
    tr7 = next(r for r in parsed.risks if r.risk_id == "TR-7")
    assert [m["task_name"] for m in tr7.monitoring] == ["Monitoring Task-5", "Monitoring Task-6"]
    assert tr7.baseline_score == 15 and tr7.residual_score == 10


def test_duplicate_rows_collapse_into_one_risk_with_monitoring_updates():
    first = row(task_name="Task-1", update_text="Started", residual_impact=3, residual_likelihood=3,
                completed_date="2026-01-01")
    second = row(task_name="Task-2", update_text="Done", residual_impact=2, residual_likelihood=2,
                 completed_date="2026-03-01")
    parsed = parse_rows(rows(first, second, row("TR-2")))
    assert parsed.row_count == 3
    assert [r.risk_id for r in parsed.risks] == ["TR-1", "TR-2"]
    tr1 = parsed.risks[0]
    assert [m["update_text"] for m in tr1.monitoring] == ["Started", "Done"]
    assert [m["residual_score"] for m in tr1.monitoring] == [9, 4]
    assert tr1.residual_score == 4  # latest completed update
    assert parsed.risks[1].monitoring == []


def test_blank_rows_are_skipped():
    blank = [None] * len(COLUMNS)
    parsed = parse_rows(rows(row(), blank))
    assert parsed.row_count == 1


def test_scores_are_recomputed_not_read_from_cells():
    parsed = parse_rows(rows(row(baseline_risk_score=99, target_residual_score=1)))
    risk = parsed.risks[0]
    assert risk.baseline_score == 12
    assert risk.target_score == 4


@pytest.mark.parametrize("impact, likelihood", [(None, 3), (4, None), (6, 3), (0, 3), (2.5, 3), ("high", 3)])
def test_missing_or_invalid_score_input_gives_null_score(impact, likelihood):
    parsed = parse_rows(rows(row(baseline_impact=impact, baseline_likelihood=likelihood)))
    assert parsed.risks[0].baseline_score is None


def test_missing_headers_are_rejected_by_name():
    header = [h for h in HEADER if h not in ("Risk Title", "Assets")]
    with pytest.raises(RegisterError, match="Risk Title, Assets"):
        parse_rows([(1, header)])


def test_name_columns_are_read_by_position():
    header = list(HEADER)
    header[23] = "Task"
    with pytest.raises(RegisterError, match=r"Name \(column 24\)"):
        parse_rows([(1, header)])


def test_other_columns_are_found_by_header_in_any_order():
    header = list(HEADER)
    header[1], header[2] = header[2], header[1]  # swap Analyst and GRC Manager
    r = row(analyst="Ana", grc_manager="Gus")
    r[1], r[2] = r[2], r[1]
    parsed = parse_rows([(1, header), (2, r)])
    assert parsed.risks[0].fields["analyst"] == "Ana"
    assert parsed.risks[0].fields["grc_manager"] == "Gus"


def test_assets_split_on_commas():
    parsed = parse_rows(rows(row(assets="Asset-412,  Asset-413 ,")))
    assert parsed.risks[0].fields["asset_ids"] == ["Asset-412", "Asset-413"]


def test_row_without_risk_id_is_rejected():
    with pytest.raises(RegisterError, match="Row 2 has no risk ID"):
        parse_rows(rows(row(risk_id=None)))


# --- Sections ---


def test_sections_split_on_labels():
    sections, structured = split_sections(ANALYSIS)
    assert structured
    assert sections == {
        "risk_statement": "Attackers could steal data.",
        "detailed_analysis": "The server is old.",
        "baseline_controls": "Firewall.",
        "exploit_paths": "(1) Remote exploit.",
    }


def test_exploit_paths_are_optional():
    sections, structured = split_sections("Risk Statement: A.\n\nBaseline Controls: B.")
    assert structured and "exploit_paths" not in sections


def test_labels_count_only_at_paragraph_start():
    text = "Risk Statement: The baseline controls: none of them apply."
    sections, _ = split_sections(text)
    assert sections == {"risk_statement": "The baseline controls: none of them apply."}


def test_unstructured_text_is_kept_raw():
    text = "Logging is not good in some places."
    sections, structured = split_sections(text)
    assert not structured
    assert sections == {"raw": text}


def test_register_sections_from_the_test_register():
    parsed = {r.risk_id: r for r in parse_workbook(REGISTER.read_bytes()).risks}
    assert set(parsed["TR-6"].sections) == {"risk_statement", "detailed_analysis", "baseline_controls", "exploit_paths"}
    assert "exploit_paths" not in parsed["TR-9"].sections
    assert not parsed["TR-17"].structured and not parsed["TR-18"].structured


# --- API ---


def upload(client, data: bytes, filename="register.xlsx"):
    return client.post("/api/register/import", files={"file": (filename, data, "application/octet-stream")})


def test_import_list_and_detail(client):
    res = upload(client, REGISTER.read_bytes(), "tactical_risk_register_test.xlsx")
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["rowCount"], body["riskCount"], body["created"], body["updated"]) == (14, 13, 13, 0)

    risks = client.get("/api/register/risks").json()
    assert len(risks) == 13
    assert [r["riskId"] for r in risks[:3]] == ["TR-6", "TR-7", "TR-8"]  # natural order
    tr17 = next(r for r in risks if r["riskId"] == "TR-17")
    assert tr17["structured"] is False and tr17["baselineScore"] == 9

    tr7 = client.get("/api/register/risks/TR-7").json()
    assert len(tr7["monitoring"]) == 2
    assert tr7["monitoring"][1]["updateText"].startswith("MFA enforced for 140")
    assert tr7["sections"]["risk_statement"].startswith("An attacker using stolen")
    assert tr7["fields"]["asset_ids"] == ["Asset-118"]

    assert client.get("/api/register/risks/TR-99").status_code == 404
    assert len(client.get("/api/register/imports").json()) == 1


def test_reimport_updates_risks_in_place(client):
    upload(client, REGISTER.read_bytes())
    res = upload(client, REGISTER.read_bytes())
    assert (res.json()["created"], res.json()["updated"]) == (0, 13)
    assert len(client.get("/api/register/risks").json()) == 13
    assert len(client.get("/api/register/risks/TR-7").json()["monitoring"]) == 2


def test_import_rejects_non_xlsx(client):
    res = upload(client, b"risk,title\n", "register.csv")
    assert res.status_code == 422
    res = upload(client, b"not a zip file", "register.xlsx")
    assert res.status_code == 422
    assert "xlsx" in res.json()["detail"]


def test_import_rejects_missing_headers(client):
    header = [h for h in HEADER if h != "Baseline Impact"]
    res = upload(client, xlsx(header=header))
    assert res.status_code == 422
    assert "Baseline Impact" in res.json()["detail"]


def test_import_allows_5_mb_but_not_more(client):
    big = b"x" * (5 * 1024 * 1024 + 10)
    res = upload(client, big)
    assert res.status_code == 413
    assert "5 MB" in res.json()["detail"]
    # The rest of the API keeps its 1 MB limit.
    res = client.post("/api/import", content=b"{" + b" " * (1024 * 1024) + b"}",
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413


# --- Internal evidence ---


def test_evidence_loaded_at_startup(client):
    sheets = {s["slug"] for s in client.get("/internal/evidence").json()}
    assert sheets == {"assets", "telemetry", "incidents", "findings", "control-tests", "vendors", "about"}
    assets = client.get("/internal/evidence/assets").json()["items"]
    assert len(assets) == 14


def test_evidence_filters_by_asset_including_multi_asset_cells(client):
    items = client.get("/internal/evidence/findings", params={"asset_id": "Asset-413"}).json()["items"]
    assert {i["recordId"] for i in items} == {"FND-1041", "FND-1042", "FND-1107"}
    assert items[0]["citation"] == "Findings FND-1041"

    tests = client.get("/internal/evidence/control-tests", params={"asset_id": ["asset-907"]}).json()["items"]
    assert [i["recordId"] for i in tests] == ["PT-064"]


def test_telemetry_rows_cite_their_spreadsheet_row_and_include_org_wide(client):
    items = client.get("/internal/evidence/telemetry", params={"asset_id": "Asset-118"}).json()["items"]
    metrics = [i["fields"]["Metric"] for i in items]
    assert "Suspected password-spraying bursts" in metrics
    org = [i for i in items if i["organizationWide"]]
    assert len(org) == 1 and org[0]["citation"].startswith("Security Telemetry Row ")


def test_incidents_filter_by_type(client):
    items = client.get("/internal/evidence/incidents", params={"type": "phishing"}).json()["items"]
    assert [i["recordId"] for i in items] == ["INC-2024-031"]
    items = client.get("/internal/evidence/incidents", params={"asset_id": "Asset-412"}).json()["items"]
    assert [i["recordId"] for i in items] == ["INC-2026-021"]
    # Cached values of formula cells are read, never recalculated.
    assert items[0]["fields"]["Total Cost (USD)"] == 6750


def test_evidence_unknown_sheet_and_misused_filter(client):
    assert client.get("/internal/evidence/payroll").status_code == 404
    assert client.get("/internal/evidence/findings", params={"type": "x"}).status_code == 422
