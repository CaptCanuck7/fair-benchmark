"""Parse a tactical risk register workbook into risks.

Rules (AGENT_BUILD.md section 4):
- The two `Name` columns are read by position (column 1 is the risk ID,
  column 24 the monitoring task). Every other column is found by its header.
- Rows sharing a risk ID repeat the risk fields and differ only in columns 24
  to 29, so they collapse into one risk with a list of monitoring updates.
- Scores are recomputed as impact x likelihood from 1-5 integers. Cached score
  cells are ignored. A missing input gives a null score.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.register.sections import split_sections
from app.xlsx import WorkbookError, open_workbook, sheet_rows

# (header, key). Positions 0 and 23 are both "Name" and are read by position.
COLUMNS: list[tuple[str, str]] = [
    ("Name", "risk_id"),
    ("Analyst", "analyst"),
    ("GRC Manager", "grc_manager"),
    ("Risk Title", "risk_title"),
    ("Risk Analysis", "risk_analysis"),
    ("Risk Category", "risk_category"),
    ("Assets", "assets"),
    ("Date Identified", "date_identified"),
    ("Business Unit", "business_unit"),
    ("Environment", "environment"),
    ("Risk Owner", "risk_owner"),
    ("Baseline Impact", "baseline_impact"),
    ("Baseline Likelihood", "baseline_likelihood"),
    ("Baseline Risk Score", "baseline_risk_score"),
    ("Risk Action", "risk_action"),
    ("Monitoring Frequency", "monitoring_frequency"),
    ("Remediation Ticket", "remediation_ticket"),
    ("Treatment Owner", "treatment_owner"),
    ("Mitigation Plan", "mitigation_plan"),
    ("Target Residual Impact", "target_residual_impact"),
    ("Target Residual Likelihood", "target_residual_likelihood"),
    ("Target Residual Score", "target_residual_score"),
    ("Due Date", "due_date"),
    ("Name", "task_name"),
    ("Monitoring Update", "update_text"),
    ("Residual Impact Score", "residual_impact"),
    ("Residual Likelihood Score", "residual_likelihood"),
    ("Residual Risk Score", "residual_score"),
    ("Completed Date", "completed_date"),
]
RISK_ID_POS, TASK_NAME_POS = 0, 23
MONITORING_KEYS = [key for _, key in COLUMNS[23:]]
RISK_KEYS = [key for _, key in COLUMNS[:23]]


class RegisterError(WorkbookError):
    pass


@dataclass
class ParsedRisk:
    risk_id: str
    fields: dict[str, Any]
    sections: dict[str, str]
    structured: bool
    baseline_score: int | None
    target_score: int | None
    residual_score: int | None
    monitoring: list[dict[str, Any]] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)


@dataclass
class ParsedRegister:
    row_count: int
    risks: list[ParsedRisk]


def _norm(header: Any) -> str:
    return re.sub(r"\s+", " ", str(header or "")).strip().lower()


def score_input(value: Any) -> int | None:
    """A 1-5 integer, or None if the cell is empty or not a valid score."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and float(value).is_integer() and 1 <= value <= 5:
        return int(value)
    return None


def score(impact: Any, likelihood: Any) -> int | None:
    i, l = score_input(impact), score_input(likelihood)
    return None if i is None or l is None else i * l


def split_assets(value: Any) -> list[str]:
    return [a.strip() for a in str(value or "").split(",") if a.strip()]


def column_map(header: list[Any]) -> dict[str, int]:
    """Map each field key to its column index, or raise naming the missing headers."""
    positions: dict[str, int] = {}
    missing: list[str] = []
    for pos, label in ((RISK_ID_POS, "Name (column 1)"), (TASK_NAME_POS, "Name (column 24)")):
        if pos < len(header) and _norm(header[pos]) == "name":
            positions[COLUMNS[pos][1]] = pos
        else:
            missing.append(label)
    by_header: dict[str, int] = {}
    for i, h in enumerate(header):
        if i not in (RISK_ID_POS, TASK_NAME_POS) and _norm(h) and _norm(h) not in by_header:
            by_header[_norm(h)] = i
    for i, (label, key) in enumerate(COLUMNS):
        if i in (RISK_ID_POS, TASK_NAME_POS):
            continue
        if _norm(label) in by_header:
            positions[key] = by_header[_norm(label)]
        else:
            missing.append(label)
    if missing:
        raise RegisterError("The register is missing these columns: " + ", ".join(missing) + ".")
    return positions


def parse_rows(rows: list[tuple[int, list[Any]]]) -> ParsedRegister:
    """Parse (row number, cells) pairs, the first being the header row."""
    if not rows:
        raise RegisterError("The register sheet is empty.")
    cols = column_map(rows[0][1])

    def get(cells: list[Any], key: str) -> Any:
        i = cols[key]
        return cells[i] if i < len(cells) else None

    risks: dict[str, ParsedRisk] = {}
    row_count = 0
    for n, cells in rows[1:]:
        if all(v is None for v in cells):
            continue
        row_count += 1
        rid = get(cells, "risk_id")
        if rid is None:
            raise RegisterError(f"Row {n} has no risk ID in the first Name column.")
        rid = str(rid)

        risk = risks.get(rid)
        if risk is None:
            fields = {key: get(cells, key) for key in RISK_KEYS}
            fields["risk_id"] = rid
            fields["asset_ids"] = split_assets(fields["assets"])
            sections, structured = split_sections(fields["risk_analysis"])
            risk = risks[rid] = ParsedRisk(
                risk_id=rid,
                fields=fields,
                sections=sections,
                structured=structured,
                baseline_score=score(fields["baseline_impact"], fields["baseline_likelihood"]),
                target_score=score(fields["target_residual_impact"], fields["target_residual_likelihood"]),
                residual_score=None,
            )
        risk.rows.append(n)

        mon = {key: get(cells, key) for key in MONITORING_KEYS}
        if any(v is not None for v in mon.values()):
            mon["residual_score"] = score(mon["residual_impact"], mon["residual_likelihood"])
            mon["residual_impact"] = score_input(mon["residual_impact"])
            mon["residual_likelihood"] = score_input(mon["residual_likelihood"])
            mon["task_name"] = None if mon["task_name"] is None else str(mon["task_name"])
            risk.monitoring.append(mon)

    for risk in risks.values():
        risk.residual_score = latest_residual(risk.monitoring)
    return ParsedRegister(row_count=row_count, risks=list(risks.values()))


def latest_residual(monitoring: list[dict[str, Any]]) -> int | None:
    """Residual score from the most recently completed update that has one."""
    scored = [(str(m.get("completed_date") or ""), i, m["residual_score"])
              for i, m in enumerate(monitoring) if m.get("residual_score") is not None]
    return max(scored)[2] if scored else None


def parse_workbook(data: bytes) -> ParsedRegister:
    wb = open_workbook(data)
    try:
        if not wb.worksheets:
            raise RegisterError("The workbook has no sheets.")
        return parse_rows(list(sheet_rows(wb.worksheets[0])))
    finally:
        wb.close()
