import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base import Base
from app.common.enums import ResultStatus


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    case_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    scenario_class: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    matchable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expected_status: Mapped[ResultStatus] = mapped_column(
        Enum(ResultStatus), nullable=False
    )


class GroundTruthLink(Base):
    __tablename__ = "ground_truth_links"

    evaluation_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)


@dataclass(frozen=True, slots=True)
class TruthCase:
    """Evaluation-only case input accepted by the independent evaluator."""

    case_id: str
    scenario_class: str
    amount: int
    matchable: bool
    expected_status: str
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Prediction:
    """Matcher output shape used by evaluation without importing matcher code."""

    case_id: str | None
    status: str
    selected_ids: tuple[str, ...] = ()
    autonomous: bool = False
    amount: int | None = None
    settlement_net: int | None = None
    stage: str | None = None
    review_status: str | None = None


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    scenario_class: str
    cases: int
    matchable_cases: int
    correctly_resolved: int
    match_rate: float
    autonomous_cases: int
    false_positives: int
    precision: float
    open_exceptions: int
    financially_unresolved_cases: int
    money_reconciled: int
    money_unresolved: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Computed benchmark/operational metrics persisted on a completed run."""

    benchmark_available: bool
    precision: float
    false_positives: int
    false_positive_rate: float
    match_rate: float
    autonomous_resolution_rate: float
    correctly_resolved: int
    matchable_cases: int
    autonomous_cases: int
    open_exceptions: int
    financially_unresolved_cases: int
    money_reconciled: int
    money_unresolved: int
    settlement_net: int
    records_processed: int
    duration_ms: int
    throughput: float
    per_class: dict[str, ClassMetrics]
    stage_metrics: dict[str, dict[str, Any]]
    review_adjusted: dict[str, Any]
    acceptance_checks: dict[str, bool]
    acceptance_passed: bool

    @property
    def benchmark_unavailable(self) -> bool:
        return not self.benchmark_available

    @property
    def source_throughput(self) -> float:
        return self.throughput
