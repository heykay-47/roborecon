import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base import Base
from app.common.enums import (
    ExceptionStatus,
    ReconciliationStage,
    ResultStatus,
    RunStatus,
)


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    """One deterministic rule observation used to explain an outcome."""

    rule_code: str
    observed_values: dict[str, Any]
    points: int
    result: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """A candidate link and the policy flags produced while scoring it."""

    candidate_id: str = ""
    score: int = 0
    evidence: tuple[CriterionEvidence, ...] = ()
    contradictions: tuple[str, ...] = ()
    duplicate: bool = False
    exact_identifier_chain: bool = False
    verified_settlement_math: bool = False


@dataclass(slots=True)
class EngineOutcome:
    """Pure engine output consumed by later persistence and evaluation tasks."""

    status: ResultStatus
    selected_ids: list[str] = field(default_factory=list)
    score: int = 0
    runner_up_score: int = 0
    margin: int = 0
    evidence: list[CriterionEvidence] = field(default_factory=list)
    candidates: list[ScoredCandidate] = field(default_factory=list)
    autonomous: bool = False
    stage: ReconciliationStage | None = None


class ReconciliationRun(Base):
    """Immutable execution envelope for one batch snapshot."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        Index(
            "uq_reconciliation_run_batch_running",
            "batch_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    throughput: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_counts: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class BatchCloseBrief(Base):
    """Append-only, read-only assessment artifact for one completed run."""

    __tablename__ = "batch_close_briefs"
    __table_args__ = (
        Index(
            "uq_batch_close_brief_run_generating",
            "run_id",
            unique=True,
            postgresql_where=text("generation_status = 'generating'"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    generation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="generating"
    )
    posture: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="human")
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    money_reconciled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    money_unresolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    financial_records_changed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    deterministic_coverage: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    ai_coverage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    themes: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    review_plan: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    citations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    generation_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stale_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReconciliationResult(Base):
    """Persisted deterministic outcome and its complete structured evidence."""

    __tablename__ = "reconciliation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    stage: Mapped[ReconciliationStage] = mapped_column(
        Enum(ReconciliationStage), nullable=False
    )
    status: Mapped[ResultStatus] = mapped_column(Enum(ResultStatus), nullable=False)
    primary_source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runner_up_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    margin: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    autonomous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selected_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )


class MatchLink(Base):
    """A persisted relationship selected by a deterministic result."""

    __tablename__ = "match_links"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_results.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="selected")
    autonomous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")


class ReconciliationException(Base):
    """Reviewable unresolved outcome without exposing benchmark truth."""

    __tablename__ = "reconciliation_exceptions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reconciliation_results.id"), nullable=True, index=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    status: Mapped[ExceptionStatus] = mapped_column(
        Enum(ExceptionStatus), nullable=False, default=ExceptionStatus.open
    )
    exception_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
