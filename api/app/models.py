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


# --- Agent support ---


class AgentRunRow(Base):
    """One agent task run: a job the api starts and the UI polls.

    `status` is queued, running, succeeded or failed. `input_hash` is a SHA-256
    of the exact input sent to the agent, so a run can be explained later.
    """

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    risk_pk: Mapped[int | None] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), nullable=True, index=True)
    analysis_id: Mapped[str | None] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), nullable=True,
                                                    index=True)
    task: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DraftRow(Base):
    """Something the agent drafted, awaiting or past review.

    `kind` is quality, triage, classification, scenario, vectors, estimate or
    report. `status` is drafted, approved, edited or rejected. An analyst's
    edit (or a triage override) is kept in `edited_payload`, beside the draft.
    """

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_pk: Mapped[int] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="drafted")
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    edited_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def effective(self) -> dict:
        """The version downstream steps use: the analyst's edit if there is one."""
        return self.edited_payload if self.status == "edited" and self.edited_payload is not None else self.payload


class OutboundLogRow(Base):
    """Every outbound request the agent attempted, allowed or blocked.

    The agent redacts register and evidence identifiers from `destination` and
    `query` before sending the entry, so the log itself holds none.
    """

    __tablename__ = "outbound_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(64))
    destination: Mapped[str] = mapped_column(Text)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
    blocked_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    at: Mapped[str] = mapped_column(String(32), index=True)


# --- Evidence gathering (AGENT_BUILD.md sections 5 and 7) ---


class EvidenceItemRow(Base):
    """A cited piece of evidence for one risk's FAIR factors.

    Agent-gathered items belong to the evidence run that found them; an answered
    data request adds an internal item with no run (`data_request_id` set).
    """

    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_pk: Mapped[int] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    data_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(16))  # internal | external
    source_type: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(Text)
    citation: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieved_at: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors: Mapped[list] = mapped_column(JSON)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class DataRequestRow(Base):
    """A question for another team, raised where a required factor has no evidence."""

    __tablename__ = "data_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_pk: Mapped[int] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    team: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    factor: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | answered
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ReferenceLibraryRow(Base):
    """A figure from an annual report (DBIR, Cost of a Data Breach, IRIS).

    It ships empty. Entries are proposed by the library refresh task or added by
    hand; only approved entries are used as evidence.
    """

    __tablename__ = "reference_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(Text)
    value: Mapped[float] = mapped_column()
    unit: Mapped[str] = mapped_column(Text)
    segment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text)
    edition: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    page: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieved_at: Mapped[str] = mapped_column(String(32))
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # proposed | approved | rejected
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)


class AppSettingRow(Base):
    """Analyst-editable settings that override .env defaults (Settings page)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON, nullable=True)


class EvidenceRunRow(Base):
    """What one evidence run did beyond its items: tool calls made, items the
    citation check rejected, and the condition-type routing used."""

    __tablename__ = "evidence_runs"

    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    risk_pk: Mapped[int] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[dict] = mapped_column(JSON, default=dict)
