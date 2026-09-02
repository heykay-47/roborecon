from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.common.api import ApiModel
from app.common.enums import (
    BatchKind,
    ExceptionStatus,
    ReconciliationStage,
    ResultStatus,
    RunStatus,
)


class CriterionEvidenceSchema(ApiModel):
    rule_code: str
    observed_values: dict[str, Any]
    points: int
    result: str
    explanation: str


class ScoredCandidateSchema(ApiModel):
    candidate_id: str
    score: int
    evidence: list[CriterionEvidenceSchema]
    contradictions: list[str]
    duplicate: bool
    exact_identifier_chain: bool
    verified_settlement_math: bool


class EngineOutcomeSchema(ApiModel):
    status: ResultStatus
    selected_ids: list[str]
    score: int
    runner_up_score: int
    margin: int
    evidence: list[CriterionEvidenceSchema]
    candidates: list[ScoredCandidateSchema]
    autonomous: bool
    stage: ReconciliationStage | None = None


class ReconciliationRunRequest(ApiModel):
    batch_id: UUID = Field(
        validation_alias="batchId",
        serialization_alias="batchId",
    )


class ClassMetricsSchema(ApiModel):
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


class EvaluationReportSchema(ApiModel):
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
    per_class: dict[str, ClassMetricsSchema]
    stage_metrics: dict[str, dict[str, Any]]
    review_adjusted: dict[str, Any]
    acceptance_checks: dict[str, bool]
    acceptance_passed: bool
    benchmark_unavailable: bool | None = None
    source_throughput: float | None = None


class ReconciliationResultResponse(ApiModel):
    result_id: UUID = Field(validation_alias="id", serialization_alias="resultId")
    stage: ReconciliationStage
    status: ResultStatus
    primary_source_type: str
    primary_source_id: UUID | None
    amount: int | None
    currency: str | None
    score: int
    runner_up_score: int
    margin: int
    autonomous: bool
    selected_ids: list[str]
    evidence: list[CriterionEvidenceSchema]
    candidates: list[ScoredCandidateSchema]


class MatchLinkResponse(ApiModel):
    link_id: UUID = Field(validation_alias="id", serialization_alias="linkId")
    result_id: UUID = Field(serialization_alias="resultId")
    source_type: str
    source_id: UUID
    role: str
    autonomous: bool
    actor: str


class ExceptionResponse(ApiModel):
    exception_id: UUID = Field(validation_alias="id", serialization_alias="exceptionId")
    result_id: UUID | None = Field(default=None, serialization_alias="resultId")
    status: ExceptionStatus
    exception_type: str
    source_type: str | None
    source_id: UUID | None
    amount: int | None
    message: str


class ReconciliationRunResponse(ApiModel):
    run_id: UUID = Field(validation_alias="id", serialization_alias="runId")
    batch_id: UUID = Field(serialization_alias="batchId")
    batch_kind: BatchKind = Field(serialization_alias="batchKind")
    status: RunStatus
    source_row_count: int
    source_counts: dict[str, int]
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    throughput: float | None
    metrics: EvaluationReportSchema | None
    error_message: str | None
    results: list[ReconciliationResultResponse] = Field(default_factory=list)
    links: list[MatchLinkResponse] = Field(default_factory=list)
    exceptions: list[ExceptionResponse] = Field(default_factory=list)


class ReconciliationRunListResponse(ApiModel):
    items: list[ReconciliationRunResponse]
    total: int
    page: int = 1
    page_size: int = 50


class ReconciliationMetricsResponse(EvaluationReportSchema):
    run_id: UUID = Field(serialization_alias="runId")
