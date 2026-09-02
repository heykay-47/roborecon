from typing import Any

from app.common.api import ApiModel
from app.common.enums import ReconciliationStage, ResultStatus


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
