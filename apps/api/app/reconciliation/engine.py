import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.common.enums import (
    LedgerEntryType,
    ReconciliationStage,
    ResultStatus,
    SettlementLineType,
)
from app.demo.dataset import (
    BankCreditSeed,
    LedgerEntrySeed,
    RazorpayOrderSeed,
    RazorpayPaymentSeed,
    RazorpayRefundSeed,
    SettlementLineSeed,
    SettlementSeed,
)
from app.reconciliation.model import (
    CriterionEvidence,
    EngineOutcome,
    ScoredCandidate,
)
from app.reconciliation.policy import can_auto_resolve

STAGE_A_DATE_WINDOW = timedelta(days=7)
STAGE_A_AMOUNT_TOLERANCE_NUMERATOR = 5
STAGE_A_AMOUNT_TOLERANCE_DENOMINATOR = 1_000
STAGE_A_MINIMUM_SCORE = 65
STAGE_B_DATE_WINDOW = timedelta(days=7)


def normalize_reference(value: str) -> str:
    """Return a stable alphanumeric token without discarding the source value."""
    return "".join(
        character
        for character in value.strip().upper()
        if character.isalnum()
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _date_distance(left: datetime, right: datetime) -> timedelta:
    return abs(_utc(left) - _utc(right))


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _evidence(
    rule_code: str,
    observed_values: dict[str, Any],
    points: int,
    result: str,
    explanation: str,
) -> CriterionEvidence:
    return CriterionEvidence(
        rule_code=rule_code,
        observed_values=observed_values,
        points=points,
        result=result,
        explanation=explanation,
    )


@dataclass(frozen=True, slots=True)
class _StageACandidate:
    record_id: str
    kind: str
    amount: int
    currency: str
    business_at: datetime
    references: tuple[str, ...]
    original_reference: str
    captured: bool
    parent_amount: int | None = None
    parent_record_id: str | None = None


def _stage_a_pool(
    orders: Iterable[RazorpayOrderSeed],
    payments: Iterable[RazorpayPaymentSeed],
    refunds: Iterable[RazorpayRefundSeed],
) -> list[_StageACandidate]:
    orders_by_provider_id = {
        order.provider_order_id: order for order in orders
    }
    payments_by_provider_id = {
        payment.provider_payment_id: payment for payment in payments
    }
    pool: list[_StageACandidate] = []

    for current_payment in payments:
        linked_order = orders_by_provider_id.get(current_payment.provider_order_id)
        references = [
            current_payment.provider_payment_id,
            current_payment.provider_order_id,
            current_payment.receipt,
        ]
        if linked_order is not None:
            references.append(linked_order.receipt)
            references.append(linked_order.provider_order_id)
        pool.append(
            _StageACandidate(
                record_id=str(current_payment.id),
                kind="payment",
                amount=current_payment.amount,
                currency=current_payment.currency,
                business_at=current_payment.business_at,
                references=tuple(references),
                original_reference=current_payment.receipt,
                captured=(
                    current_payment.captured
                    and _status_value(current_payment.status) == "captured"
                ),
            )
        )

    for current_refund in refunds:
        parent_payment = payments_by_provider_id.get(
            current_refund.provider_payment_id
        )
        references = [
            current_refund.provider_refund_id,
            current_refund.provider_payment_id,
        ]
        if parent_payment is not None:
            references.extend((parent_payment.receipt, parent_payment.provider_order_id))
        pool.append(
            _StageACandidate(
                record_id=str(current_refund.id),
                kind="refund",
                amount=current_refund.amount,
                currency=current_refund.currency,
                business_at=current_refund.business_at,
                references=tuple(references),
                original_reference=current_refund.provider_refund_id,
                captured=(
                    parent_payment is not None
                    and parent_payment.captured
                    and _status_value(parent_payment.status) == "captured"
                ),
                parent_amount=(
                    parent_payment.amount if parent_payment is not None else None
                ),
                parent_record_id=(
                    str(parent_payment.id) if parent_payment is not None else None
                ),
            )
        )

    return pool


def _matching_identifier(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> str | None:
    normalized_entry = normalize_reference(entry.reference)
    if not normalized_entry:
        return None
    for reference in candidate.references:
        if normalize_reference(reference) == normalized_entry:
            return reference
    return None


def _is_exact_identifier(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> bool:
    return _matching_identifier(entry, candidate) is not None


def _amount_window(entry_amount: int, candidate_amount: int) -> int:
    amount_basis = max(abs(entry_amount), abs(candidate_amount))
    tolerance = (
        amount_basis * STAGE_A_AMOUNT_TOLERANCE_NUMERATOR
    ) // STAGE_A_AMOUNT_TOLERANCE_DENOMINATOR
    return max(100, tolerance)


def _reference_similarity(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> float:
    normalized_entry = normalize_reference(entry.reference)
    entry_digits = "".join(re.findall(r"\d+", normalized_entry))
    similarities = []
    for reference in candidate.references:
        normalized_reference = normalize_reference(reference)
        reference_digits = "".join(re.findall(r"\d+", normalized_reference))
        if entry_digits and entry_digits == reference_digits:
            similarities.append(0.85)
            continue
        similarities.append(
            SequenceMatcher(
                None,
                normalized_entry,
                normalized_reference,
            ).ratio()
        )
    return max(
        similarities,
    )


def _numeric_reference_key(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> str:
    entry_digits = "".join(re.findall(r"\d+", normalize_reference(entry.reference)))
    if not entry_digits:
        return ""
    for reference in candidate.references:
        if "".join(re.findall(r"\d+", normalize_reference(reference))) == entry_digits:
            return entry_digits
    return ""


def _same_reference(left: str, right: str) -> bool:
    normalized_left = normalize_reference(left)
    normalized_right = normalize_reference(right)
    return bool(normalized_left) and normalized_left == normalized_right


def _has_reference_evidence(candidate: ScoredCandidate) -> bool:
    return any(
        evidence.rule_code == "REFERENCE" and evidence.points > 0
        for evidence in candidate.evidence
    )


def _batch_collision_ids(
    candidate: ScoredCandidate,
    reserved_ids: set[str],
    resource_ids: Iterable[str] | None = None,
) -> list[str]:
    resources = set(resource_ids or (candidate.candidate_id,))
    return sorted(reserved_ids.intersection(resources))


def _mark_batch_collision(
    candidate: ScoredCandidate,
    reserved_ids: set[str],
    resource_ids: Iterable[str] | None = None,
) -> ScoredCandidate:
    collision_ids = _batch_collision_ids(candidate, reserved_ids, resource_ids)
    if not collision_ids:
        return candidate
    return replace(
        candidate,
        contradictions=tuple(
            dict.fromkeys((*candidate.contradictions, "batch_collision"))
        ),
        duplicate=True,
        evidence=(
            *candidate.evidence,
            _evidence(
                "BATCH_COLLISION",
                {
                    "candidate_id": candidate.candidate_id,
                    "consumed_ids": collision_ids,
                },
                0,
                "fail",
                "A source record was already selected for another batch record.",
            ),
        ),
    )


def _amount_compatible(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> bool:
    if candidate.kind == "refund":
        return (
            candidate.amount > 0
            and candidate.parent_amount is not None
            and candidate.amount <= candidate.parent_amount
            and entry.amount in (candidate.amount, candidate.parent_amount)
        )
    return abs(candidate.amount - entry.amount) <= _amount_window(
        entry.amount, candidate.amount
    )


def _eligible_stage_a(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> bool:
    if _is_exact_identifier(entry, candidate):
        # Exact identifiers are useful search keys, not contradiction overrides.
        return True
    if candidate.currency != entry.currency:
        return False
    if not _amount_compatible(entry, candidate):
        return False
    return _date_distance(entry.business_at, candidate.business_at) <= STAGE_A_DATE_WINDOW


def _stage_a_score(
    entry: LedgerEntrySeed,
    candidate: _StageACandidate,
) -> ScoredCandidate:
    evidence: list[CriterionEvidence] = []
    contradictions: list[str] = []
    score = 0
    matched_identifier = _matching_identifier(entry, candidate)
    exact_identifier = matched_identifier is not None
    normalized_entry = normalize_reference(entry.reference)
    normalized_reference = normalize_reference(candidate.original_reference)

    if candidate.currency == entry.currency:
        evidence.append(
            _evidence(
                "CURRENCY",
                {"ledger_currency": entry.currency, "provider_currency": candidate.currency},
                0,
                "pass",
                "Ledger and provider currency agree.",
            )
        )
    else:
        contradictions.append("currency_contradiction")
        evidence.append(
            _evidence(
                "CURRENCY",
                {"ledger_currency": entry.currency, "provider_currency": candidate.currency},
                0,
                "fail",
                "Currency contradiction blocks autonomous resolution.",
            )
        )

    if exact_identifier:
        score += 45
        reference_result = "pass"
        reference_points = 45
        reference_explanation = "A normalized ledger reference is in the provider identifier chain."
    else:
        similarity = _reference_similarity(entry, candidate)
        if similarity >= 0.9:
            reference_points = 30
            score += reference_points
            reference_result = "pass"
        elif similarity >= 0.75:
            reference_points = 20
            score += reference_points
            reference_result = "weak"
        else:
            reference_points = 0
            reference_result = "fail"
        reference_explanation = "Reference similarity is bounded and does not establish identity alone."
    reference_observed_values: dict[str, Any] = {
        "ledger_reference": entry.reference,
        "provider_reference": candidate.original_reference,
        "normalized_ledger_reference": normalized_entry,
        "normalized_provider_reference": normalized_reference,
    }
    if matched_identifier is not None:
        reference_observed_values.update(
            {
                "matched_provider_identifier": matched_identifier,
                "normalized_matched_provider_identifier": normalize_reference(
                    matched_identifier
                ),
            }
        )
    evidence.append(
        _evidence(
            "REFERENCE",
            reference_observed_values,
            reference_points,
            reference_result,
            reference_explanation,
        )
    )

    if candidate.kind == "payment":
        amount_matches = candidate.amount == entry.amount
        amount_explanation = "Captured payment amount equals ledger amount."
    else:
        amount_matches = (
            candidate.parent_amount is not None
            and candidate.amount <= candidate.parent_amount
            and entry.amount in (candidate.amount, candidate.parent_amount)
        )
        amount_explanation = "Refund amount is positive and does not exceed its captured payment."

    if amount_matches:
        score += 35
        evidence.append(
            _evidence(
                "AMOUNT",
                {"ledger_amount": entry.amount, "provider_amount": candidate.amount},
                35,
                "pass",
                amount_explanation,
            )
        )
    else:
        contradictions.append("amount_contradiction")
        evidence.append(
            _evidence(
                "AMOUNT",
                {"ledger_amount": entry.amount, "provider_amount": candidate.amount},
                0,
                "fail",
                "Amount evidence does not satisfy the source direction and equality rules.",
            )
        )

    date_distance = _date_distance(entry.business_at, candidate.business_at)
    if date_distance <= timedelta(days=1):
        date_points = 10
        date_result = "pass"
    elif date_distance <= STAGE_A_DATE_WINDOW:
        date_points = 5
        date_result = "weak"
    else:
        date_points = 0
        date_result = "fail"
        contradictions.append("date_contradiction")
    score += date_points
    evidence.append(
        _evidence(
            "DATE",
            {
                "distance_hours": round(date_distance.total_seconds() / 3600, 2),
                "window_days": STAGE_A_DATE_WINDOW.days,
            },
            date_points,
            date_result,
            "Business timestamps are scored only inside the candidate window.",
        )
    )

    if candidate.captured:
        score += 10
        lifecycle_result = "pass"
    else:
        contradictions.append("lifecycle_contradiction")
        lifecycle_result = "fail"
    evidence.append(
        _evidence(
            "LIFECYCLE",
            {"captured": candidate.captured, "record_type": candidate.kind},
            10 if candidate.captured else 0,
            lifecycle_result,
            "Only captured payments and refunds with a captured parent can reconcile.",
        )
    )

    return ScoredCandidate(
        candidate_id=candidate.record_id,
        score=score,
        evidence=tuple(evidence),
        contradictions=tuple(contradictions),
        exact_identifier_chain=exact_identifier,
    )


def _outcome_from_stage_a_candidates(
    entry: LedgerEntrySeed,
    candidates: list[ScoredCandidate],
    reserved_candidate_ids: set[str] | None = None,
) -> EngineOutcome:
    if not candidates:
        return EngineOutcome(
            status=ResultStatus.missing_razorpay,
            evidence=[
                _evidence(
                    "MISSING_RAZORPAY",
                    {"ledger_id": str(entry.id), "ledger_reference": entry.reference},
                    0,
                    "fail",
                    "No eligible Razorpay record was found in this batch.",
                )
            ],
            stage=ReconciliationStage.ledger_to_razorpay,
        )

    reserved_candidate_ids = reserved_candidate_ids or set()
    selectable_candidates = [
        candidate
        for candidate in candidates
        if candidate.candidate_id not in reserved_candidate_ids
    ] or candidates
    exact_candidates = [
        candidate
        for candidate in selectable_candidates
        if candidate.exact_identifier_chain
    ]
    if len(exact_candidates) > 1:
        candidates = [
            replace(candidate, duplicate=True)
            if candidate in exact_candidates
            else candidate
            for candidate in candidates
        ]
        selectable_candidates = [
            candidate
            for candidate in candidates
            if candidate.candidate_id not in reserved_candidate_ids
        ] or candidates
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.candidate_id))
    selectable_candidates.sort(
        key=lambda candidate: (-candidate.score, candidate.candidate_id)
    )
    selected = selectable_candidates[0]
    runner_up = selectable_candidates[1] if len(selectable_candidates) > 1 else None
    runner_up_score = runner_up.score if runner_up is not None else 0
    margin = selected.score - runner_up_score
    if (
        not selected.exact_identifier_chain
        and not _has_reference_evidence(selected)
        and selected.score < STAGE_A_MINIMUM_SCORE
    ):
        return EngineOutcome(
            status=ResultStatus.missing_razorpay,
            score=selected.score,
            runner_up_score=runner_up_score,
            margin=margin,
            evidence=[
                *selected.evidence,
                _evidence(
                    "MINIMUM_EVIDENCE",
                    {"minimum_score": STAGE_A_MINIMUM_SCORE},
                    0,
                    "fail",
                    "No bounded candidate cleared the minimum evidence bar.",
                ),
            ],
            candidates=candidates,
            stage=ReconciliationStage.ledger_to_razorpay,
        )
    duplicate_candidates = [
        candidate for candidate in selectable_candidates if candidate.duplicate
    ]
    duplicate = bool(duplicate_candidates) or len(exact_candidates) > 1
    if duplicate:
        status = ResultStatus.duplicate
    elif selected.contradictions:
        status = ResultStatus.amount_mismatch
    elif runner_up is not None and margin < 15:
        status = ResultStatus.ambiguous
    else:
        status = ResultStatus.matched

    autonomous = (
        status is not ResultStatus.ambiguous
        and can_auto_resolve(selected, runner_up)
    )
    return EngineOutcome(
        status=status,
        selected_ids=(
            [candidate.candidate_id for candidate in selectable_candidates if candidate.duplicate]
            if duplicate
            else [selected.candidate_id]
        ),
        score=selected.score,
        runner_up_score=runner_up_score,
        margin=margin,
        evidence=list(selected.evidence),
        candidates=candidates,
        autonomous=autonomous,
        stage=ReconciliationStage.ledger_to_razorpay,
    )


def reconcile_stage_a(
    ledger: list[LedgerEntrySeed],
    orders: list[RazorpayOrderSeed],
    payments: list[RazorpayPaymentSeed],
    refunds: list[RazorpayRefundSeed],
) -> list[EngineOutcome]:
    """Reconcile ledger entries to captured Razorpay payments or refunds."""
    pool = _stage_a_pool(orders, payments, refunds)
    outcomes: list[EngineOutcome] = []
    considered_ids: set[str] = set()
    reserved_ids: set[str] = set()

    for entry in ledger:
        expected_kind = (
            "refund" if entry.entry_type == LedgerEntryType.refund else "payment"
        )
        eligible = [
            candidate
            for candidate in pool
            if candidate.kind == expected_kind and _eligible_stage_a(entry, candidate)
        ]
        scored = [_stage_a_score(entry, candidate) for candidate in eligible]
        reference_counts = Counter(
            _numeric_reference_key(entry, candidate)
            for candidate in eligible
        )
        duplicate_keys = {
            key for key, count in reference_counts.items() if key and count > 1
        }
        scored = [
            replace(scored_candidate, duplicate=True)
            if _numeric_reference_key(entry, source_candidate) in duplicate_keys
            else scored_candidate
            for scored_candidate, source_candidate in zip(scored, eligible)
        ]
        collision_candidate_ids = {
            scored_candidate.candidate_id
            for scored_candidate in scored
            if _batch_collision_ids(scored_candidate, reserved_ids)
        }
        scored = [
            _mark_batch_collision(scored_candidate, reserved_ids)
            for scored_candidate in scored
        ]
        for source_candidate, scored_candidate in zip(eligible, scored):
            if not (
                scored_candidate.exact_identifier_chain
                or _has_reference_evidence(scored_candidate)
                or scored_candidate.score >= STAGE_A_MINIMUM_SCORE
            ):
                continue
            considered_ids.add(scored_candidate.candidate_id)
            if source_candidate.parent_record_id is not None:
                considered_ids.add(source_candidate.parent_record_id)
        outcome = _outcome_from_stage_a_candidates(
            entry,
            scored,
            reserved_candidate_ids=collision_candidate_ids,
        )
        outcomes.append(outcome)
        if outcome.autonomous:
            reserved_ids.update(outcome.selected_ids)

    for candidate in pool:
        if candidate.record_id in considered_ids:
            continue
        outcomes.append(
            EngineOutcome(
                status=ResultStatus.missing_ledger,
                selected_ids=[candidate.record_id],
                candidates=[ScoredCandidate(candidate_id=candidate.record_id)],
                evidence=[
                    _evidence(
                        "MISSING_LEDGER",
                        {
                            "provider_id": candidate.record_id,
                            "provider_reference": candidate.original_reference,
                        },
                        0,
                        "fail",
                        "No ledger entry was found for this provider record.",
                    )
                ],
                stage=ReconciliationStage.ledger_to_razorpay,
            )
        )

    return outcomes


@dataclass(frozen=True, slots=True)
class _SettlementFacts:
    settlement: SettlementSeed
    captured_credits: int
    refund_debits: int
    fee_debits: int
    tax_debits: int
    held_amount: int
    release_adjustments: int
    explicit_adjustments: int
    expected_amount: int
    contradictions: tuple[str, ...]
    evidence: tuple[CriterionEvidence, ...]


def _line_kind(line: SettlementLineSeed) -> str:
    return _status_value(line.line_type)


def _settlement_facts(
    current_settlement: SettlementSeed,
    lines: list[SettlementLineSeed],
) -> _SettlementFacts:
    captured_credits = 0
    refund_debits = 0
    fee_debits = 0
    tax_debits = 0
    held_amount = 0
    release_adjustments = 0
    explicit_adjustments = 0
    contradictions: list[str] = []
    observed_lines: dict[str, int] = {}

    for current_line in lines:
        kind = _line_kind(current_line)
        observed_lines[kind] = observed_lines.get(kind, 0) + current_line.amount
        if current_line.currency != current_settlement.currency:
            contradictions.append("line_currency_contradiction")
        if kind == SettlementLineType.payment.value:
            if current_line.amount < 0:
                contradictions.append("payment_direction_contradiction")
            captured_credits += current_line.amount
        elif kind == SettlementLineType.refund.value:
            if current_line.amount > 0:
                contradictions.append("refund_direction_contradiction")
            else:
                refund_debits += -current_line.amount
        elif kind == SettlementLineType.fee.value:
            if current_line.amount > 0:
                contradictions.append("fee_direction_contradiction")
            else:
                fee_debits += -current_line.amount
        elif kind == SettlementLineType.tax.value:
            if current_line.amount > 0:
                contradictions.append("tax_direction_contradiction")
            else:
                tax_debits += -current_line.amount
        elif kind == SettlementLineType.hold.value:
            if current_line.amount > 0:
                contradictions.append("hold_direction_contradiction")
            else:
                held_amount += -current_line.amount
        elif kind == SettlementLineType.release.value:
            if current_line.amount < 0:
                contradictions.append("release_direction_contradiction")
            else:
                release_adjustments += current_line.amount
        elif kind == SettlementLineType.adjustment.value:
            explicit_adjustments += current_line.amount

    expected_amount = (
        captured_credits
        - refund_debits
        - fee_debits
        - tax_debits
        - held_amount
        + release_adjustments
        + explicit_adjustments
    )
    if current_settlement.amount != expected_amount:
        contradictions.append("settlement_amount_contradiction")
    if current_settlement.fee != fee_debits:
        contradictions.append("settlement_fee_contradiction")
    if current_settlement.tax != tax_debits:
        contradictions.append("settlement_tax_contradiction")
    if current_settlement.held_amount != held_amount:
        contradictions.append("settlement_hold_contradiction")

    evidence = (
        _evidence(
            "SETTLEMENT_MATH",
            {
                "captured_credits": captured_credits,
                "refund_debits": refund_debits,
                "fee_debits": fee_debits,
                "tax_debits": tax_debits,
                "held_amount": held_amount,
                "release_adjustments": release_adjustments,
                "explicit_adjustments": explicit_adjustments,
                "expected_amount": expected_amount,
                "reported_amount": current_settlement.amount,
                "line_totals": observed_lines,
            },
            50 if not contradictions else 0,
            "pass" if not contradictions else "fail",
            "Settlement net equals captured credits less debits plus release and adjustment values.",
        ),
    )
    return _SettlementFacts(
        settlement=current_settlement,
        captured_credits=captured_credits,
        refund_debits=refund_debits,
        fee_debits=fee_debits,
        tax_debits=tax_debits,
        held_amount=held_amount,
        release_adjustments=release_adjustments,
        explicit_adjustments=explicit_adjustments,
        expected_amount=expected_amount,
        contradictions=tuple(dict.fromkeys(contradictions)),
        evidence=evidence,
    )


def _bank_match(
    current_settlement: SettlementSeed,
    credits: list[BankCreditSeed],
) -> tuple[BankCreditSeed | None, bool, bool, list[CriterionEvidence], tuple[str, ...]]:
    exact = [
        credit
        for credit in credits
        if normalize_reference(credit.utr)
        == normalize_reference(current_settlement.utr)
    ]
    if exact:
        selected = sorted(exact, key=lambda credit: str(credit.id))[0]
        contradictions: list[str] = []
        if len(exact) > 1:
            contradictions.append("bank_duplicate_contradiction")
        if selected.currency != current_settlement.currency:
            contradictions.append("bank_currency_contradiction")
        if selected.amount != current_settlement.amount:
            contradictions.append("bank_amount_contradiction")
        evidence = [
            _evidence(
                "BANK_UTR",
                {
                    "settlement_utr": current_settlement.utr,
                    "bank_utr": selected.utr,
                    "settlement_amount": current_settlement.amount,
                    "bank_amount": selected.amount,
                },
                25 if not contradictions else 0,
                "pass" if not contradictions else "fail",
                "Bank credit was selected by exact UTR before amount/date evidence.",
            )
        ]
        return selected, True, len(exact) == 1 and not contradictions, evidence, tuple(contradictions)

    eligible = [
        credit
        for credit in credits
        if credit.currency == current_settlement.currency
        and credit.amount == current_settlement.amount
        and _date_distance(credit.business_at, current_settlement.business_at)
        <= STAGE_B_DATE_WINDOW
    ]
    if not eligible:
        return (
            None,
            False,
            False,
            [
                _evidence(
                    "BANK_CREDIT",
                    {"settlement_utr": current_settlement.utr},
                    0,
                    "fail",
                    "No bank credit matched by UTR or bounded amount/date evidence.",
                )
            ],
            (),
        )
    selected = sorted(
        eligible,
        key=lambda credit: (
            _date_distance(credit.business_at, current_settlement.business_at),
            str(credit.id),
        ),
    )[0]
    contradictions = ("bank_duplicate_contradiction",) if len(eligible) > 1 else ()
    return (
        selected,
        False,
        False,
        [
            _evidence(
                "BANK_AMOUNT_DATE",
                {
                    "settlement_amount": current_settlement.amount,
                    "bank_amount": selected.amount,
                    "settlement_utr": current_settlement.utr,
                    "bank_utr": selected.utr,
                },
                15 if not contradictions else 0,
                "pass" if not contradictions else "fail",
                "Amount/date fallback is allowed only after no exact UTR was found.",
            )
        ],
        contradictions,
    )


def _release_lines(
    held_settlement: SettlementSeed,
    settlements: list[SettlementSeed],
    lines_by_settlement: dict[Any, list[SettlementLineSeed]],
) -> list[tuple[SettlementSeed, SettlementLineSeed]]:
    held_reference = normalize_reference(held_settlement.provider_settlement_id)
    return [
        (current_settlement, current_line)
        for current_settlement in settlements
        if current_settlement.id != held_settlement.id
        for current_line in lines_by_settlement.get(current_settlement.id, [])
        if _line_kind(current_line) == SettlementLineType.release.value
        and normalize_reference(current_line.reference) == held_reference
        and _utc(current_line.business_at) > _utc(held_settlement.business_at)
    ]


def _release_settlements(
    held_settlement: SettlementSeed,
    settlements: list[SettlementSeed],
    lines_by_settlement: dict[Any, list[SettlementLineSeed]],
) -> list[SettlementSeed]:
    release_ids = {
        current_settlement.id
        for current_settlement, _ in _release_lines(
            held_settlement, settlements, lines_by_settlement
        )
    }
    return [
        current_settlement
        for current_settlement in settlements
        if current_settlement.id in release_ids
    ]


def _stage_b_candidate(
    current_payment: RazorpayPaymentSeed,
    base_settlement: SettlementSeed,
    related_settlements: list[SettlementSeed],
    facts_by_id: dict[Any, _SettlementFacts],
    lines_by_settlement: dict[Any, list[SettlementLineSeed]],
    refunds_by_payment: dict[str, list[RazorpayRefundSeed]],
    credits: list[BankCreditSeed],
) -> tuple[ScoredCandidate, list[str], list[str]]:
    evidence: list[CriterionEvidence] = []
    contradictions: list[str] = []
    selected_ids = [str(settlement.id) for settlement in related_settlements]
    currency_matches = all(
        current_payment.currency == settlement.currency
        for settlement in related_settlements
    )
    evidence.append(
        _evidence(
            "CURRENCY",
            {
                "payment_currency": current_payment.currency,
                "settlement_currencies": [
                    settlement.currency for settlement in related_settlements
                ],
            },
            0,
            "pass" if currency_matches else "fail",
            "Payment and settlement currencies must agree.",
        )
    )
    if not currency_matches:
        contradictions.append("currency_contradiction")
    payment_lines = [
        current_line
        for related_settlement in related_settlements
        for current_line in lines_by_settlement.get(related_settlement.id, [])
        if _line_kind(current_line) == SettlementLineType.payment.value
        and _same_reference(current_line.reference, current_payment.provider_payment_id)
    ]
    if not payment_lines or any(
        current_line.amount != current_payment.amount for current_line in payment_lines
    ):
        contradictions.append("payment_amount_contradiction")
    evidence.append(
        _evidence(
            "CAPTURED_PAYMENT",
            {
                "provider_payment_id": current_payment.provider_payment_id,
                "reported_amount": current_payment.amount,
                "line_amounts": [current_line.amount for current_line in payment_lines],
            },
            10 if payment_lines and "payment_amount_contradiction" not in contradictions else 0,
            "pass" if payment_lines and "payment_amount_contradiction" not in contradictions else "fail",
            "Captured payment credit is linked by provider payment ID.",
        )
    )

    payment_refunds = refunds_by_payment.get(current_payment.provider_payment_id, [])
    for current_refund in payment_refunds:
        if current_refund.currency != current_payment.currency:
            contradictions.append("refund_currency_contradiction")
        if current_refund.amount > current_payment.amount:
            contradictions.append("refund_amount_contradiction")
        refund_lines = [
            current_line
            for related_settlement in related_settlements
            for current_line in lines_by_settlement.get(related_settlement.id, [])
            if _line_kind(current_line) == SettlementLineType.refund.value
            and _same_reference(current_line.reference, current_payment.provider_payment_id)
        ]
        if not any(
            current_line.amount == -current_refund.amount
            for current_line in refund_lines
        ):
            contradictions.append("refund_amount_contradiction")
    if payment_refunds:
        evidence.append(
            _evidence(
                "REFUND_DIRECTION",
                {
                    "refund_amounts": [refund.amount for refund in payment_refunds],
                    "settlement_refund_lines": [
                        current_line.amount
                        for related_settlement in related_settlements
                        for current_line in lines_by_settlement.get(related_settlement.id, [])
                        if _line_kind(current_line) == SettlementLineType.refund.value
                        and _same_reference(
                            current_line.reference,
                            current_payment.provider_payment_id,
                        )
                    ],
                },
                0 if any("refund_amount_contradiction" in item for item in contradictions) else 10,
                "fail" if any("refund_amount_contradiction" in item for item in contradictions) else "pass",
                "Refund source amounts must be represented as negative settlement debits.",
            )
        )

    for related_settlement in related_settlements:
        facts = facts_by_id[related_settlement.id]
        evidence.extend(facts.evidence)
        contradictions.extend(facts.contradictions)

    hold_settlements = [
        related_settlement
        for related_settlement in related_settlements
        if facts_by_id[related_settlement.id].held_amount > 0
    ]
    if hold_settlements:
        for held_settlement in hold_settlements:
            release_settlements = [
                related_settlement
                for related_settlement in related_settlements
                if related_settlement.id != held_settlement.id
            ]
            release_entries = _release_lines(
                held_settlement,
                release_settlements,
                lines_by_settlement,
            )
            released_amount = sum(
                current_line.amount
                for _, current_line in release_entries
            )
            release_ids = list(
                dict.fromkeys(
                    str(current_settlement.id)
                    for current_settlement, _ in release_entries
                )
            )
            release_ok = bool(release_entries) and released_amount == facts_by_id[
                held_settlement.id
            ].held_amount
            if not release_ok:
                contradictions.append("hold_release_missing")
            evidence.append(
                _evidence(
                    "HOLD_RELEASE",
                    {
                        "held_settlement_id": str(held_settlement.id),
                        "held_amount": facts_by_id[held_settlement.id].held_amount,
                        "released_amount": released_amount,
                        "release_settlement_ids": release_ids,
                    },
                    10 if release_ok else 0,
                    "pass" if release_ok else "fail",
                    "Held value closes only after a later release settlement is evidenced.",
                )
            )

    exact_bank_count = 0
    for related_settlement in related_settlements:
        selected_credit, exact_utr, bank_verified, bank_evidence, bank_contradictions = _bank_match(
            related_settlement, credits
        )
        evidence.extend(bank_evidence)
        contradictions.extend(bank_contradictions)
        if selected_credit is None:
            contradictions.append("bank_credit_missing")
        else:
            selected_ids.append(str(selected_credit.id))
        if exact_utr and bank_verified:
            exact_bank_count += 1

    contradictions = list(dict.fromkeys(contradictions))
    math_verified = not any(
        contradiction
        for contradiction in contradictions
        if contradiction != "bank_credit_missing"
    )
    all_bank_verified = exact_bank_count == len(related_settlements)
    score = 50 if math_verified else 0
    score += 10 if payment_lines and "payment_amount_contradiction" not in contradictions else 0
    score += 25 if all_bank_verified else 15 if exact_bank_count else 0
    score += 10 if hold_settlements and "hold_release_missing" not in contradictions else 0
    score = min(score, 100)
    candidate = ScoredCandidate(
        candidate_id=str(base_settlement.id),
        score=score,
        evidence=tuple(evidence),
        contradictions=tuple(contradictions),
        verified_settlement_math=math_verified and all_bank_verified,
    )
    return candidate, selected_ids, contradictions


def reconcile_stage_b(
    payments: list[RazorpayPaymentSeed],
    refunds: list[RazorpayRefundSeed],
    settlements: list[SettlementSeed],
    lines: list[SettlementLineSeed],
    credits: list[BankCreditSeed],
) -> list[EngineOutcome]:
    """Reconcile captured payments through settlement arithmetic and bank credits."""
    lines_by_settlement: dict[Any, list[SettlementLineSeed]] = {}
    for current_line in lines:
        lines_by_settlement.setdefault(current_line.settlement_id, []).append(current_line)
    facts_by_id = {
        current_settlement.id: _settlement_facts(
            current_settlement,
            lines_by_settlement.get(current_settlement.id, []),
        )
        for current_settlement in settlements
    }
    refunds_by_payment: dict[str, list[RazorpayRefundSeed]] = {}
    for current_refund in refunds:
        refunds_by_payment.setdefault(current_refund.provider_payment_id, []).append(
            current_refund
        )

    outcomes: list[EngineOutcome] = []
    reserved_ids: set[str] = set()
    for current_payment in payments:
        if not current_payment.captured or _status_value(current_payment.status) != "captured":
            continue
        base_settlements = [
            current_settlement
            for current_settlement in settlements
            if any(
                _line_kind(current_line) == SettlementLineType.payment.value
                and _same_reference(current_line.reference, current_payment.provider_payment_id)
                for current_line in lines_by_settlement.get(current_settlement.id, [])
            )
        ]
        if not base_settlements:
            outcomes.append(
                EngineOutcome(
                    status=ResultStatus.missing_settlement,
                    evidence=[
                        _evidence(
                            "MISSING_SETTLEMENT",
                            {"provider_payment_id": current_payment.provider_payment_id},
                            0,
                            "fail",
                            "No settlement line links this captured payment to a settlement.",
                        )
                    ],
                    stage=ReconciliationStage.razorpay_to_settlement,
                )
            )
            continue

        scored_candidates: list[ScoredCandidate] = []
        selected_ids_by_candidate: dict[str, list[str]] = {}
        candidate_contradictions: dict[str, list[str]] = {}
        collision_candidate_ids: set[str] = set()
        for base_settlement in base_settlements:
            releases = _release_settlements(
                base_settlement, settlements, lines_by_settlement
            )
            related_settlements = [base_settlement, *releases]
            candidate, selected_ids, contradictions = _stage_b_candidate(
                current_payment,
                base_settlement,
                related_settlements,
                facts_by_id,
                lines_by_settlement,
                refunds_by_payment,
                credits,
            )
            if _batch_collision_ids(candidate, reserved_ids, selected_ids):
                collision_candidate_ids.add(candidate.candidate_id)
            candidate = _mark_batch_collision(
                candidate,
                reserved_ids,
                selected_ids,
            )
            contradictions = list(candidate.contradictions)
            scored_candidates.append(candidate)
            selected_ids_by_candidate[candidate.candidate_id] = selected_ids
            candidate_contradictions[candidate.candidate_id] = contradictions

        selectable_candidates = [
            candidate
            for candidate in scored_candidates
            if candidate.candidate_id not in collision_candidate_ids
        ] or scored_candidates
        scored_candidates.sort(
            key=lambda candidate: (-candidate.score, candidate.candidate_id)
        )
        selectable_candidates.sort(
            key=lambda candidate: (-candidate.score, candidate.candidate_id)
        )
        selected = selectable_candidates[0]
        runner_up = (
            selectable_candidates[1] if len(selectable_candidates) > 1 else None
        )
        runner_up_score = runner_up.score if runner_up is not None else 0
        margin = selected.score - runner_up_score
        selected_contradictions = candidate_contradictions[selected.candidate_id]
        if selected.duplicate:
            status = ResultStatus.duplicate
        elif "hold_release_missing" in selected_contradictions:
            status = ResultStatus.missing_settlement
        elif "bank_credit_missing" in selected_contradictions:
            status = ResultStatus.missing_bank_credit
        elif selected_contradictions:
            status = ResultStatus.amount_mismatch
        elif runner_up is not None and margin < 15:
            status = ResultStatus.ambiguous
        else:
            status = ResultStatus.matched
        outcome = EngineOutcome(
            status=status,
            selected_ids=selected_ids_by_candidate[selected.candidate_id],
            score=selected.score,
            runner_up_score=runner_up_score,
            margin=margin,
            evidence=list(selected.evidence),
            candidates=scored_candidates,
            autonomous=(
                status is not ResultStatus.ambiguous
                and can_auto_resolve(selected, runner_up)
            ),
            stage=ReconciliationStage.razorpay_to_settlement,
        )
        outcomes.append(outcome)
        if outcome.autonomous:
            reserved_ids.update(outcome.selected_ids)

    return outcomes
