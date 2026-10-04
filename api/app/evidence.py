"""Mock internal evidence: load mock_internal_evidence.xlsx into one table per sheet.

The workbook stands in for what the SOC, Asset Management and other teams
would supply. Rows join to register risks through asset IDs, never risk IDs.
The tables are reloaded from the file on every start, so editing the workbook
and restarting the api container picks up the change.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    EvidenceAbout,
    EvidenceAsset,
    EvidenceControlTest,
    EvidenceFinding,
    EvidenceIncident,
    EvidenceRecord,
    EvidenceTelemetry,
    EvidenceVendor,
)
from app.register.parser import split_assets
from app.xlsx import WorkbookError, open_workbook, sheet_rows

log = logging.getLogger(__name__)

EVIDENCE_FILE = "mock_internal_evidence.xlsx"
ORG_WIDE = "organization-wide"


@dataclass(frozen=True)
class Sheet:
    slug: str  # used in /internal/evidence/{slug}
    title: str  # sheet name in the workbook, used in citations
    model: type[EvidenceRecord]
    id_column: str | None  # None: the record ID is "Row N"
    asset_column: str | None


SHEETS: list[Sheet] = [
    Sheet("assets", "Asset Inventory", EvidenceAsset, "Asset ID", "Asset ID"),
    Sheet("telemetry", "Security Telemetry", EvidenceTelemetry, None, "Asset ID"),
    Sheet("incidents", "Incident History", EvidenceIncident, "Incident ID", "Asset / Area"),
    Sheet("findings", "Findings", EvidenceFinding, "Finding ID", "Asset ID"),
    Sheet("control-tests", "Control Tests and Assessments", EvidenceControlTest, "Record ID", "Asset ID"),
    Sheet("vendors", "Vendor Assessments", EvidenceVendor, "Asset ID", "Asset ID"),
    Sheet("about", "About", EvidenceAbout, "Item", None),
]
SHEETS_BY_SLUG = {s.slug: s for s in SHEETS}


def load_evidence(session: Session, path: Path) -> dict[str, int] | None:
    """Replace the evidence tables with the workbook's contents. Returns rows per sheet."""
    if not path.is_file():
        log.warning("Mock evidence file not found at %s; internal evidence is empty.", path)
        return None
    try:
        wb = open_workbook(path)
    except WorkbookError:
        log.exception("Could not read mock evidence file %s", path)
        return None

    counts: dict[str, int] = {}
    try:
        for sheet in SHEETS:
            session.execute(delete(sheet.model))
            if sheet.title not in wb.sheetnames:
                log.warning("Mock evidence sheet %r is missing.", sheet.title)
                counts[sheet.slug] = 0
                continue
            rows = list(sheet_rows(wb[sheet.title]))
            if not rows:
                counts[sheet.slug] = 0
                continue
            headers = [str(h) if h is not None else f"Column {i + 1}" for i, h in enumerate(rows[0][1])]
            n_loaded = 0
            for n, cells in rows[1:]:
                if all(v is None for v in cells):
                    continue
                fields = {h: (cells[i] if i < len(cells) else None) for i, h in enumerate(headers)}
                rid = fields.get(sheet.id_column) if sheet.id_column else None
                session.add(sheet.model(
                    record_id=str(rid) if rid is not None else f"Row {n}",
                    row_number=n,
                    asset_ids=split_assets(fields.get(sheet.asset_column)) if sheet.asset_column else [],
                    fields=fields,
                ))
                n_loaded += 1
            counts[sheet.slug] = n_loaded
        session.commit()
    finally:
        wb.close()
    log.info("Loaded mock internal evidence: %s", counts)
    return counts


def citation(sheet: Sheet, record_id: str) -> str:
    return f"{sheet.title} {record_id}"


def record_out(sheet: Sheet, row: EvidenceRecord) -> dict:
    return {
        "sheet": sheet.title,
        "recordId": row.record_id,
        "citation": citation(sheet, row.record_id),
        "row": row.row_number,
        "assetIds": row.asset_ids,
        "organizationWide": any(a.lower() == ORG_WIDE for a in row.asset_ids),
        "fields": row.fields,
    }


def query_sheet(session: Session, sheet: Sheet, asset_ids: list[str] | None = None,
                incident_type: str | None = None) -> list[dict]:
    """Rows of one sheet. With asset IDs, only rows naming one of them, plus
    organization-wide rows (which apply to every asset). With an incident type,
    only incidents whose Type contains it (case-insensitive)."""
    rows = session.scalars(select(sheet.model).order_by(sheet.model.row_number)).all()
    wanted = {a.lower() for a in asset_ids or [] if a.strip()}
    out = []
    for row in rows:
        ids = {a.lower() for a in row.asset_ids}
        if wanted and not (ids & wanted or ORG_WIDE in ids):
            continue
        if incident_type and incident_type.lower() not in str(row.fields.get("Type") or "").lower():
            continue
        out.append(record_out(sheet, row))
    return out
