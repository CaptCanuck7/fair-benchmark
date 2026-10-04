"""The identifier denylist for the agent's outbound guard (AGENT_BUILD.md section 8).

Built from the imported register and the mock internal evidence. The agent
blocks any outbound query or URL that contains one of these values. Matching
happens in the agent (agent/app/guard.py); this module only collects them.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EvidenceAsset,
    EvidenceControlTest,
    EvidenceFinding,
    EvidenceIncident,
    EvidenceTelemetry,
    EvidenceVendor,
    RiskRow,
)

# Job titles stripped from people's names ("VP Ben Nakamura" -> "Ben Nakamura").
_TITLES = re.compile(r"^(?:vp|svp|evp|cio|ciso|cto|dr|mr|mrs|ms|mx)\.?\s+", re.IGNORECASE)
MIN_LENGTH = 3


def person_variants(name: str) -> list[str]:
    """The name as written, without a leading title, and the surname alone."""
    out = [name]
    bare = _TITLES.sub("", name).strip()
    if bare != name:
        out.append(bare)
    parts = bare.split()
    if len(parts) >= 2:
        out.append(parts[-1])
    return out


def build_identifiers(session: Session) -> list[dict]:
    found: dict[tuple[str, str], None] = {}

    def add(kind: str, value) -> None:
        if value is None:
            return
        value = re.sub(r"\s+", " ", str(value)).strip()
        if len(value) >= MIN_LENGTH:
            found[(kind, value)] = None

    for risk in session.scalars(select(RiskRow)):
        f = risk.fields
        add("risk_id", risk.risk_id)
        add("ticket_id", f.get("remediation_ticket"))
        for key in ("analyst", "grc_manager", "risk_owner", "treatment_owner"):
            if f.get(key):
                for v in person_variants(str(f[key])):
                    add("person", v)
        add("business_unit", f.get("business_unit"))
        add("environment", f.get("environment"))
        for a in f.get("asset_ids", []):
            add("asset_id", a)
        for m in risk.monitoring:
            add("risk_id", m.task_name)

    for row in session.scalars(select(EvidenceAsset)):
        add("asset_id", row.record_id)
        add("asset_name", row.fields.get("Asset Name"))
        add("business_unit", row.fields.get("Business Unit"))
        add("environment", row.fields.get("Environment"))
    for model in (EvidenceTelemetry, EvidenceFinding, EvidenceControlTest, EvidenceVendor, EvidenceIncident):
        for row in session.scalars(select(model)):
            for a in row.asset_ids:
                if a.lower().startswith("asset-"):
                    add("asset_id", a)
    for row in session.scalars(select(EvidenceIncident)):
        add("incident_id", row.record_id)
    for row in session.scalars(select(EvidenceFinding)):
        add("finding_id", row.record_id)
    for row in session.scalars(select(EvidenceControlTest)):
        add("record_id", row.record_id)

    return [{"kind": k, "value": v} for k, v in found]
