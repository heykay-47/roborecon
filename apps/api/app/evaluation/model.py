import uuid
from dataclasses import dataclass

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
class TruthSource:
    source_type: str
    source_id: str


@dataclass(frozen=True, slots=True)
class TruthCase:
    """Evaluation-only case input accepted by the independent evaluator."""

    case_id: str
    scenario_class: str
    amount: int
    matchable: bool
    expected_status: str
    sources: tuple[TruthSource, ...] = ()

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self.sources)


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
class StageMetrics:
    eligible_cases: int
    correctly_resolved: int
    correctness_rate: float
    autonomous_cases: int
    autonomy_rate: float
    autonomous_links: int
    false_positives: int
    precision: float
    unresolved_cases: int
    open_exceptions: int
    records_processed: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Computed benchmark/operational metrics persisted on a completed run."""

    benchmark_available: bool
    precision: float | None
    false_positives: int | None
    false_positive_rate: float | None
    match_rate: float | None
    end_to_end_autonomy_rate: float | None
    exception_recall: float | None
    correctly_resolved: int | None
    matchable_cases: int | None
    autonomous_cases: int | None
    open_exceptions: int
    financially_unresolved_cases: int | None
    money_reconciled: int | None
    money_unresolved: int | None
    settlement_net: int
    records_processed: int
    duration_ms: int
    throughput: float
    per_class: dict[str, ClassMetrics] | None
    stage_metrics: dict[str, StageMetrics] | None
    review_adjusted: dict[str, object]
    acceptance_checks: dict[str, bool]
    acceptance_passed: bool

    @property
    def benchmark_unavailable(self) -> bool:
        return not self.benchmark_available

    @property
    def source_throughput(self) -> float:
        return self.throughput
