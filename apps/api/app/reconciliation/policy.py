from app.reconciliation.model import ScoredCandidate

AUTONOMOUS_SCORE = 90
AUTONOMOUS_MARGIN = 15


def can_auto_resolve(
    candidate: ScoredCandidate,
    runner_up: ScoredCandidate | None,
) -> bool:
    """Apply the only authority boundary allowed to deterministic outcomes."""
    margin = candidate.score - (runner_up.score if runner_up else 0)
    return (
        not candidate.contradictions
        and not candidate.duplicate
        and (
            candidate.exact_identifier_chain
            or candidate.verified_settlement_math
            or (candidate.score >= AUTONOMOUS_SCORE and margin >= AUTONOMOUS_MARGIN)
        )
    )
