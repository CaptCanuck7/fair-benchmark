"""Database tables. Timestamps are ISO-8601 UTC strings, matching the document."""

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AnalysisRow(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    document: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32), index=True)

    runs: Mapped[list["RunRow"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True,
        order_by="RunRow.run_at.desc()",
    )


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[str] = mapped_column(String(32), index=True)
    iterations: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger)
    input_hash: Mapped[str] = mapped_column(String(64))
    document_snapshot: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON)

    analysis: Mapped[AnalysisRow] = relationship(back_populates="runs")


# --- Tactical risk register (AGENT_BUILD.md section 5) ---


class RegisterImportRow(Base):
    __tablename__ = "register_imports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(String(32), index=True)
    row_count: Mapped[int] = mapped_column(Integer)
    risk_count: Mapped[int] = mapped_column(Integer)


class RiskRow(Base):
    """One register risk. Re-importing a risk ID updates this row in place."""

    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("register_imports.id"), index=True)
    risk_id: Mapped[str] = mapped_column(String(128), unique=True)
    fields: Mapped[dict] = mapped_column(JSON)
    sections: Mapped[dict] = mapped_column(JSON)
    structured: Mapped[bool] = mapped_column(Boolean)
    baseline_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    monitoring: Mapped[list["RiskMonitoringRow"]] = relationship(
        back_populates="risk", cascade="all, delete-orphan", passive_deletes=True,
        order_by="RiskMonitoringRow.id",
    )


class RiskMonitoringRow(Base):
    __tablename__ = "risk_monitoring"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_pk: Mapped[int] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    task_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    residual_impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_likelihood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    risk: Mapped[RiskRow] = relationship(back_populates="monitoring")


# --- Mock internal evidence: one table per sheet of mock_internal_evidence.xlsx ---


class EvidenceRecord:
    """Columns shared by every evidence sheet table.

    `record_id` is the sheet's own ID column where it has one, else "Row N"
    (the spreadsheet row). `fields` holds the row keyed by the sheet's headers.
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(128), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    asset_ids: Mapped[list] = mapped_column(JSON)
    fields: Mapped[dict] = mapped_column(JSON)


class EvidenceAsset(EvidenceRecord, Base):
    __tablename__ = "evidence_asset_inventory"


class EvidenceTelemetry(EvidenceRecord, Base):
    __tablename__ = "evidence_security_telemetry"


class EvidenceIncident(EvidenceRecord, Base):
    __tablename__ = "evidence_incident_history"


class EvidenceFinding(EvidenceRecord, Base):
    __tablename__ = "evidence_findings"


class EvidenceControlTest(EvidenceRecord, Base):
    __tablename__ = "evidence_control_tests"


class EvidenceVendor(EvidenceRecord, Base):
    __tablename__ = "evidence_vendor_assessments"


class EvidenceAbout(EvidenceRecord, Base):
    __tablename__ = "evidence_about"
