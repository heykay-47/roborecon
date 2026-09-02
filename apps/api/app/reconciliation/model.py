from dataclasses import dataclass, field
from typing import Any

from app.common.enums import ReconciliationStage, ResultStatus


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
