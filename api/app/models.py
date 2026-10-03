"""Database tables. Timestamps are ISO-8601 UTC strings, matching the document."""

from sqlalchemy import JSON, BigInteger, ForeignKey, Integer, String, Text
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
