from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

import pytest

from app.common.enums import (
    LedgerEntryType,
    RazorpayPaymentStatus,
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
from app.reconciliation.engine import (
    _amount_window,
    reconcile_stage_a,
    reconcile_stage_b,
)
from app.reconciliation.model import ScoredCandidate
from app.reconciliation.policy import can_auto_resolve
from app.reconciliation.schema import EngineOutcomeSchema

NAMESPACE = UUID("5b5c9f44-95cc-4bb6-a9b9-34a4cfe8d0f4")
NOW = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


def ident(kind: str) -> UUID:
    return uuid5(NAMESPACE, kind)


def ledger(
    key: str = "one",
    *,
    reference: str = "RCPT-001",
    amount: int = 10_000,
    currency: str = "INR",
    entry_type: LedgerEntryType = LedgerEntryType.payment,
    business_at: datetime = NOW,
) -> LedgerEntrySeed:
    return LedgerEntrySeed(
        id=ident(f"ledger-{key}"),
        reference=reference,
        entry_type=entry_type,
        amount=amount,
        currency=currency,
        business_at=business_at,
    )


def order(
    key: str = "one",
    *,
    provider_order_id: str = "order_001",
    receipt: str = "RCPT-001",
    amount: int = 10_000,
    currency: str = "INR",
    business_at: datetime = NOW,
) -> RazorpayOrderSeed:
    return RazorpayOrderSeed(
        id=ident(f"order-{key}"),
        provider_order_id=provider_order_id,
        receipt=receipt,
        amount=amount,
        currency=currency,
        status="paid",
        business_at=business_at,
    )


def payment(
    key: str = "one",
    *,
    provider_payment_id: str | None = None,
    provider_order_id: str = "order_001",
    receipt: str = "RCPT-001",
    amount: int = 10_000,
    currency: str = "INR",
    status: RazorpayPaymentStatus = RazorpayPaymentStatus.captured,
    captured: bool = True,
    business_at: datetime = NOW,
) -> RazorpayPaymentSeed:
    return RazorpayPaymentSeed(
        id=ident(f"payment-{key}"),
        provider_payment_id=provider_payment_id or f"pay_{key}",
        provider_order_id=provider_order_id,
        receipt=receipt,
        amount=amount,
        currency=currency,
        status=status,
        captured=captured,
        business_at=business_at,
    )


def refund(
    key: str = "one",
    *,
    provider_payment_id: str = "pay_one",
    amount: int = 2_000,
    currency: str = "INR",
    business_at: datetime = NOW + timedelta(days=1),
) -> RazorpayRefundSeed:
    return RazorpayRefundSeed(
        id=ident(f"refund-{key}"),
        provider_refund_id=f"rfnd_{key}",
        provider_payment_id=provider_payment_id,
        amount=amount,
        currency=currency,
        status="processed",
        business_at=business_at,
    )


def settlement(
    key: str = "one",
    *,
    provider_settlement_id: str | None = None,
    amount: int = 9_764,
    fee: int = 200,
    tax: int = 36,
    held_amount: int = 0,
    currency: str = "INR",
    utr: str | None = None,
    business_at: datetime = NOW + timedelta(days=2),
) -> SettlementSeed:
    return SettlementSeed(
        id=ident(f"settlement-{key}"),
        provider_settlement_id=provider_settlement_id or f"setl_{key}",
        amount=amount,
        fee=fee,
        tax=tax,
        held_amount=held_amount,
        currency=currency,
        utr=utr or f"UTR-{key}",
        status="processed",
        business_at=business_at,
    )


def line(
    key: str,
    settlement_id: UUID,
    line_type: SettlementLineType,
    reference: str,
    amount: int,
    *,
    business_at: datetime = NOW + timedelta(days=2),
) -> SettlementLineSeed:
    return SettlementLineSeed(
        id=ident(f"line-{key}"),
        settlement_id=settlement_id,
        line_type=line_type,
        reference=reference,
        amount=amount,
        currency="INR",
        business_at=business_at,
    )


def credit(
    key: str,
    settlement_id: UUID,
    *,
    utr: str,
    amount: int,
    business_at: datetime = NOW + timedelta(days=3),
) -> BankCreditSeed:
    return BankCreditSeed(
        id=ident(f"credit-{key}"),
        settlement_id=settlement_id,
        utr=utr,
        amount=amount,
        currency="INR",
        business_at=business_at,
    )


def stage_a_case(name: str):
    if name == "exact_unique":
        return [ledger()], [order()], [payment()], []
    if name == "duplicate":
        return [ledger()], [order()], [payment("one"), payment("two")], []
    if name == "fuzzy_low_margin":
        return (
            [ledger(reference="ORDER-1001")],
            [],
            [
                payment("one", receipt="ORDER-1000"),
                payment("two", receipt="ORDER-1002"),
            ],
            [],
        )
    if name == "missing_payment":
        return [ledger()], [order()], [], []
    if name == "amount_mismatch":
        return [ledger()], [order(amount=10_500)], [payment(amount=10_500)], []
    raise AssertionError(f"unknown fixture {name}")


@pytest.mark.parametrize(
    ("fixture_name", "expected_status", "autonomous"),
    [
        ("exact_unique", "matched", True),
        ("duplicate", "duplicate", False),
        ("fuzzy_low_margin", "ambiguous", False),
        ("missing_payment", "missing_razorpay", False),
        ("amount_mismatch", "amount_mismatch", False),
    ],
)
def test_stage_a_policy(fixture_name, expected_status, autonomous):
    outcome = reconcile_stage_a(*stage_a_case(fixture_name))[0]

    assert outcome.status.value == expected_status
    assert outcome.autonomous is autonomous


def test_stage_a_emits_missing_ledger_for_provider_only_payment():
    outcomes = reconcile_stage_a([], [], [payment()], [])

    assert len(outcomes) == 1
    assert outcomes[0].status is ResultStatus.missing_ledger
    assert outcomes[0].autonomous is False


def test_stage_a_normalizes_reference_but_preserves_original_value():
    outcomes = reconcile_stage_a(
        [ledger(reference=" inv / 001 online ")],
        [],
        [payment(receipt="INV-001-ONLINE")],
        [],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert any(
        item.observed_values.get("ledger_reference") == " inv / 001 online "
        and item.observed_values.get("normalized_ledger_reference") == "INV001ONLINE"
        for item in outcomes[0].evidence
    )


def test_stage_a_refund_evidence_preserves_refund_reference():
    outcomes = reconcile_stage_a(
        [
            ledger(
                reference="RFND-ONE",
                amount=2_000,
                entry_type=LedgerEntryType.refund,
                business_at=NOW + timedelta(days=1),
            )
        ],
        [order()],
        [payment()],
        [refund()],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert any(
        item.observed_values.get("provider_reference") == "rfnd_one"
        for item in outcomes[0].evidence
    )


def test_stage_a_exact_chain_evidence_identifies_matching_provider_identifier():
    outcomes = reconcile_stage_a(
        [ledger(reference="PAY-EXACT")],
        [],
        [payment(provider_payment_id="PAY-EXACT", receipt="RECEIPT-ORIGINAL")],
        [],
    )

    reference_evidence = next(
        item for item in outcomes[0].evidence if item.rule_code == "REFERENCE"
    )
    assert reference_evidence.observed_values["matched_provider_identifier"] == "PAY-EXACT"
    assert (
        reference_evidence.observed_values["normalized_matched_provider_identifier"]
        == "PAYEXACT"
    )


def test_stage_a_does_not_reuse_provider_payment_across_ledger_entries():
    shared_payment = payment()

    outcomes = reconcile_stage_a(
        [ledger("first"), ledger("second")],
        [order()],
        [shared_payment],
        [],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert outcomes[0].autonomous is True
    assert outcomes[1].status is ResultStatus.duplicate
    assert outcomes[1].autonomous is False
    assert any(item.rule_code == "BATCH_COLLISION" for item in outcomes[1].evidence)


def test_stage_a_does_not_reuse_provider_refund_across_ledger_entries():
    outcomes = reconcile_stage_a(
        [
            ledger(
                "first",
                reference="RFND-ONE",
                amount=2_000,
                entry_type=LedgerEntryType.refund,
                business_at=NOW + timedelta(days=1),
            ),
            ledger(
                "second",
                reference="RFND-ONE",
                amount=2_000,
                entry_type=LedgerEntryType.refund,
                business_at=NOW + timedelta(days=1),
            ),
        ],
        [order()],
        [payment()],
        [refund()],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert outcomes[0].autonomous is True
    assert outcomes[1].status is ResultStatus.duplicate
    assert outcomes[1].autonomous is False


def test_stage_a_collision_does_not_suppress_unused_alternative():
    shared = payment(
        "shared",
        provider_payment_id="PAY-SHARED",
        receipt="SHARED-RECEIPT",
    )
    alternative = payment(
        "alternative",
        provider_payment_id="PAY-ALTERNATIVE",
        receipt="ALTERNATIVE-RECEIPT",
    )

    outcomes = reconcile_stage_a(
        [
            ledger("first", reference="PAY-SHARED"),
            ledger("second", reference="PAY-ALTERNATIVE"),
        ],
        [order()],
        [shared, alternative],
        [],
    )

    assert outcomes[0].selected_ids == [str(shared.id)]
    assert outcomes[0].autonomous is True
    assert outcomes[1].status is ResultStatus.matched
    assert outcomes[1].selected_ids == [str(alternative.id)]
    assert outcomes[1].autonomous is True


def test_stage_a_ambiguous_result_does_not_reserve_provisional_provider_id():
    ambiguous = payment(
        "ambiguous",
        provider_payment_id="PAY-AMBIGUOUS",
        receipt="RCPT-001",
        business_at=NOW + timedelta(days=2),
    )
    runner_up = payment(
        "runner-up",
        provider_order_id="order_runner",
        receipt="RCPT-0012",
    )

    outcomes = reconcile_stage_a(
        [
            ledger("ambiguous", reference="RCPT-001"),
            ledger("after-ambiguous", reference="PAY-AMBIGUOUS"),
        ],
        [order()],
        [ambiguous, runner_up],
        [],
    )

    assert outcomes[0].status is ResultStatus.ambiguous
    assert outcomes[0].autonomous is False
    assert outcomes[1].status is ResultStatus.matched
    assert outcomes[1].selected_ids == [str(ambiguous.id)]
    assert outcomes[1].autonomous is True


def test_exact_identifier_does_not_bypass_currency_contradiction():
    outcomes = reconcile_stage_a(
        [ledger(currency="INR")],
        [order(currency="USD")],
        [payment(currency="USD")],
        [],
    )

    assert outcomes[0].status is ResultStatus.amount_mismatch
    assert outcomes[0].autonomous is False
    assert any("currency" in code for code in outcomes[0].candidates[0].contradictions)


def test_exact_identifier_does_not_bypass_date_contradiction():
    outcomes = reconcile_stage_a(
        [ledger()],
        [order(business_at=NOW + timedelta(days=30))],
        [payment(business_at=NOW + timedelta(days=30))],
        [],
    )

    assert outcomes[0].status is ResultStatus.amount_mismatch
    assert outcomes[0].autonomous is False
    assert "date_contradiction" in outcomes[0].candidates[0].contradictions


def test_stage_a_candidate_generation_excludes_far_and_different_currency_records():
    outcomes = reconcile_stage_a(
        [ledger()],
        [],
        [
            payment("near"),
            payment(
                "far",
                receipt="OTHER-999",
                business_at=NOW + timedelta(days=30),
            ),
            payment("usd", receipt="OTHER-USD", currency="USD"),
        ],
        [],
    )

    assert [candidate.candidate_id for candidate in outcomes[0].candidates] == [
        str(ident("payment-near"))
    ]


def test_stage_a_keeps_bounded_candidate_when_reference_similarity_is_low():
    bounded = payment("bounded", receipt="UNRELATED-PAYMENT")

    outcome = reconcile_stage_a(
        [ledger(reference="LEDGER-REFERENCE")],
        [],
        [bounded],
        [],
    )[0]

    assert [candidate.candidate_id for candidate in outcome.candidates] == [
        str(bounded.id)
    ]
    assert outcome.autonomous is False


def test_stage_a_does_not_link_or_consume_low_evidence_candidate():
    bounded = payment("bounded", receipt="UNRELATED-PAYMENT")

    outcomes = reconcile_stage_a(
        [ledger(reference="LEDGER-REFERENCE")],
        [],
        [bounded],
        [],
    )

    assert outcomes[0].status is ResultStatus.missing_razorpay
    assert outcomes[0].selected_ids == []
    assert outcomes[1].status is ResultStatus.missing_ledger


def test_stage_a_excludes_numeric_reference_candidate_outside_amount_bound():
    mismatched = payment(
        "mismatched",
        receipt="CHECKOUT-100",
        amount=10_500,
    )

    outcomes = reconcile_stage_a(
        [ledger(reference="INV-100", amount=10_000)],
        [],
        [mismatched],
        [],
    )

    assert outcomes[0].status is ResultStatus.missing_razorpay
    assert outcomes[0].selected_ids == []
    assert outcomes[1].status is ResultStatus.missing_ledger


def test_stage_a_amount_window_uses_integer_half_percent_rounding():
    amount = 9_276_516_075_116_799

    assert _amount_window(amount, amount) == amount * 5 // 1_000


@pytest.mark.parametrize(
    ("score", "runner_up_score", "expected"),
    [(89, 0, False), (90, 0, True), (100, 86, False), (100, 85, True)],
)
def test_autonomous_score_and_margin_boundaries(score, runner_up_score, expected):
    candidate = ScoredCandidate(candidate_id="selected", score=score)
    runner_up = (
        ScoredCandidate(candidate_id="runner-up", score=runner_up_score)
        if runner_up_score
        else None
    )

    assert can_auto_resolve(candidate, runner_up) is expected


def test_exact_chain_and_verified_math_are_tier_one_guardrails():
    assert can_auto_resolve(
        ScoredCandidate(candidate_id="exact", score=0, exact_identifier_chain=True),
        None,
    )
    assert can_auto_resolve(
        ScoredCandidate(candidate_id="math", score=0, verified_settlement_math=True),
        None,
    )
    assert not can_auto_resolve(
        ScoredCandidate(
            candidate_id="contradiction",
            score=100,
            exact_identifier_chain=True,
            contradictions=("currency_contradiction",),
        ),
        None,
    )
    assert not can_auto_resolve(
        ScoredCandidate(candidate_id="duplicate", score=100, duplicate=True), None
    )


def test_stage_b_verifies_fee_gst_arithmetic_and_bank_credit():
    current_payment = payment()
    current_settlement = settlement()
    lines = [
        line("payment", current_settlement.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]

    outcomes = reconcile_stage_b(
        [current_payment],
        [],
        [current_settlement],
        lines,
        [credit("one", current_settlement.id, utr="UTR-one", amount=9_764)],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert outcomes[0].autonomous is True
    assert any(item.rule_code == "SETTLEMENT_MATH" for item in outcomes[0].evidence)
    assert any(item.rule_code == "BANK_UTR" for item in outcomes[0].evidence)


def test_stage_b_does_not_reuse_settlement_or_bank_credit_across_payments():
    first_payment = payment("first", amount=6_000)
    second_payment = payment("second", amount=4_000)
    current_settlement = settlement()
    lines = [
        line(
            "payment-first",
            current_settlement.id,
            SettlementLineType.payment,
            "pay_first",
            6_000,
        ),
        line(
            "payment-second",
            current_settlement.id,
            SettlementLineType.payment,
            "pay_second",
            4_000,
        ),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]

    outcomes = reconcile_stage_b(
        [first_payment, second_payment],
        [],
        [current_settlement],
        lines,
        [credit("one", current_settlement.id, utr="UTR-one", amount=9_764)],
    )

    assert outcomes[0].status is ResultStatus.matched
    assert outcomes[0].autonomous is True
    assert outcomes[1].status is ResultStatus.duplicate
    assert outcomes[1].autonomous is False
    assert any(item.rule_code == "BATCH_COLLISION" for item in outcomes[1].evidence)


def test_stage_b_collision_does_not_suppress_unused_alternative():
    first_payment = payment("first", provider_payment_id="pay_first", amount=6_000)
    second_payment = payment("second", provider_payment_id="pay_second", amount=4_000)
    shared = settlement("shared", amount=9_764, utr="UTR-shared")
    alternative = settlement(
        "alternative",
        amount=4_000,
        fee=0,
        tax=0,
        utr="UTR-alternative",
    )
    lines = [
        line("shared-first", shared.id, SettlementLineType.payment, "pay_first", 6_000),
        line("shared-second", shared.id, SettlementLineType.payment, "pay_second", 4_000),
        line("shared-fee", shared.id, SettlementLineType.fee, "FEE-shared", -200),
        line("shared-tax", shared.id, SettlementLineType.tax, "GST-shared", -36),
        line(
            "alternative-second",
            alternative.id,
            SettlementLineType.payment,
            "pay_second",
            4_000,
        ),
    ]

    outcomes = reconcile_stage_b(
        [first_payment, second_payment],
        [],
        [shared, alternative],
        lines,
        [
            credit("shared", shared.id, utr="UTR-shared", amount=9_764),
            credit(
                "alternative",
                alternative.id,
                utr="UTR-alternative-fallback",
                amount=4_000,
            ),
        ],
    )

    assert outcomes[0].selected_ids == [str(shared.id), str(ident("credit-shared"))]
    assert outcomes[0].autonomous is True
    assert outcomes[1].status is ResultStatus.matched
    assert str(alternative.id) in outcomes[1].selected_ids
    assert str(shared.id) not in outcomes[1].selected_ids
    assert outcomes[1].autonomous is False


def test_stage_b_ambiguous_result_does_not_reserve_provisional_settlement_or_bank_ids():
    ambiguous_payment = payment("ambiguous", provider_payment_id="pay_ambiguous")
    after_payment = payment("after", provider_payment_id="pay_after")
    provisional = settlement("a", amount=19_764, utr="UTR-a")
    runner_up = settlement("b", amount=9_764, utr="UTR-b")
    lines = [
        line(
            "a-ambiguous",
            provisional.id,
            SettlementLineType.payment,
            "pay_ambiguous",
            10_000,
        ),
        line("a-after", provisional.id, SettlementLineType.payment, "pay_after", 10_000),
        line("a-fee", provisional.id, SettlementLineType.fee, "FEE-a", -200),
        line("a-tax", provisional.id, SettlementLineType.tax, "GST-a", -36),
        line(
            "b-ambiguous",
            runner_up.id,
            SettlementLineType.payment,
            "pay_ambiguous",
            10_000,
        ),
        line("b-fee", runner_up.id, SettlementLineType.fee, "FEE-b", -200),
        line("b-tax", runner_up.id, SettlementLineType.tax, "GST-b", -36),
    ]

    outcomes = reconcile_stage_b(
        [ambiguous_payment, after_payment],
        [],
        [provisional, runner_up],
        lines,
        [
            credit("a", provisional.id, utr="UTR-a", amount=19_764),
            credit("b", runner_up.id, utr="UTR-b", amount=9_764),
        ],
    )

    assert outcomes[0].status is ResultStatus.ambiguous
    assert outcomes[0].autonomous is False
    assert outcomes[1].status is ResultStatus.matched
    assert outcomes[1].selected_ids == [str(provisional.id), str(ident("credit-a"))]
    assert outcomes[1].autonomous is True


def test_stage_b_normalizes_payment_line_reference_before_linking():
    current_payment = payment()
    current_settlement = settlement()
    lines = [
        line(
            "payment",
            current_settlement.id,
            SettlementLineType.payment,
            " PAY-ONE ",
            10_000,
        ),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]
    outcome = reconcile_stage_b(
        [current_payment],
        [],
        [current_settlement],
        lines,
        [credit("one", current_settlement.id, utr="UTR-one", amount=9_764)],
    )[0]

    assert outcome.status is ResultStatus.matched
    assert outcome.autonomous is True


def test_stage_b_rejects_refund_line_with_wrong_direction():
    current_payment = payment()
    current_settlement = settlement(amount=7_764)
    lines = [
        line("payment", current_settlement.id, SettlementLineType.payment, "pay_one", 10_000),
        line("refund", current_settlement.id, SettlementLineType.refund, "pay_one", 2_000),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]

    outcome = reconcile_stage_b(
        [current_payment],
        [refund()],
        [current_settlement],
        lines,
        [credit("one", current_settlement.id, utr="UTR-one", amount=7_764)],
    )[0]

    assert outcome.status is ResultStatus.amount_mismatch
    assert outcome.autonomous is False
    assert any(item.rule_code == "REFUND_DIRECTION" for item in outcome.evidence)


def test_stage_b_matches_bank_credit_by_utr_before_amount_and_date():
    current_payment = payment()
    current_settlement = settlement()
    lines = [
        line("payment", current_settlement.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]
    wrong_utr = credit("wrong", current_settlement.id, utr="UTR-other", amount=9_764)
    right_utr = credit("right", current_settlement.id, utr="UTR-one", amount=9_764)

    outcome = reconcile_stage_b(
        [current_payment],
        [],
        [current_settlement],
        lines,
        [wrong_utr, right_utr],
    )[0]

    assert outcome.status is ResultStatus.matched
    assert str(right_utr.id) in outcome.selected_ids
    assert str(wrong_utr.id) not in outcome.selected_ids


def test_stage_b_reports_missing_bank_credit_after_valid_settlement_math():
    current_payment = payment()
    current_settlement = settlement()
    lines = [
        line("payment", current_settlement.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", current_settlement.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", current_settlement.id, SettlementLineType.tax, "GST-001", -36),
    ]

    outcome = reconcile_stage_b(
        [current_payment], [], [current_settlement], lines, []
    )[0]

    assert outcome.status is ResultStatus.missing_bank_credit
    assert outcome.autonomous is False


def test_stage_b_requires_hold_and_later_release_settlements():
    current_payment = payment()
    held = settlement(
        "held",
        amount=8_764,
        held_amount=1_000,
        provider_settlement_id="setl_held",
        utr="UTR-held",
    )
    release = settlement(
        "release",
        amount=1_000,
        fee=0,
        tax=0,
        provider_settlement_id="setl_release",
        utr="UTR-release",
        business_at=NOW + timedelta(days=4),
    )
    lines = [
        line("payment", held.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", held.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", held.id, SettlementLineType.tax, "GST-001", -36),
        line("hold", held.id, SettlementLineType.hold, "HOLD-001", -1_000),
        line(
            "release",
            release.id,
            SettlementLineType.release,
            "setl_held",
            1_000,
            business_at=release.business_at,
        ),
    ]
    credits = [
        credit("held", held.id, utr="UTR-held", amount=8_764),
        credit("release", release.id, utr="UTR-release", amount=1_000),
    ]

    outcome = reconcile_stage_b(
        [current_payment], [], [held, release], lines, credits
    )[0]

    assert outcome.status is ResultStatus.matched
    assert outcome.autonomous is True
    assert str(held.id) in outcome.selected_ids
    assert str(release.id) in outcome.selected_ids
    assert any(item.rule_code == "HOLD_RELEASE" for item in outcome.evidence)


def test_stage_b_hold_release_ignores_unrelated_release_lines():
    current_payment = payment()
    held = settlement(
        "held-unrelated",
        amount=8_764,
        held_amount=1_000,
        provider_settlement_id="setl_held-unrelated",
        utr="UTR-held-unrelated",
    )
    release = settlement(
        "release-unrelated",
        amount=1_500,
        fee=0,
        tax=0,
        provider_settlement_id="setl_release-unrelated",
        utr="UTR-release-unrelated",
        business_at=NOW + timedelta(days=4),
    )
    lines = [
        line("payment", held.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", held.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", held.id, SettlementLineType.tax, "GST-001", -36),
        line("hold", held.id, SettlementLineType.hold, "HOLD-001", -1_000),
        line(
            "release-matching",
            release.id,
            SettlementLineType.release,
            "setl_held-unrelated",
            1_000,
            business_at=release.business_at,
        ),
        line(
            "release-unrelated",
            release.id,
            SettlementLineType.release,
            "setl-other-held",
            500,
            business_at=release.business_at,
        ),
    ]

    outcome = reconcile_stage_b(
        [current_payment],
        [],
        [held, release],
        lines,
        [
            credit("held-unrelated", held.id, utr="UTR-held-unrelated", amount=8_764),
            credit(
                "release-unrelated",
                release.id,
                utr="UTR-release-unrelated",
                amount=1_500,
            ),
        ],
    )[0]

    assert outcome.status is ResultStatus.matched
    assert outcome.autonomous is True
    assert any(
        item.rule_code == "HOLD_RELEASE" and item.observed_values["released_amount"] == 1_000
        for item in outcome.evidence
    )


def test_stage_b_keeps_hold_open_without_a_later_release():
    current_payment = payment()
    held = settlement(
        "held-only",
        amount=8_764,
        held_amount=1_000,
        provider_settlement_id="setl_held-only",
        utr="UTR-held-only",
    )
    lines = [
        line("payment", held.id, SettlementLineType.payment, "pay_one", 10_000),
        line("fee", held.id, SettlementLineType.fee, "FEE-001", -200),
        line("tax", held.id, SettlementLineType.tax, "GST-001", -36),
        line("hold", held.id, SettlementLineType.hold, "HOLD-001", -1_000),
    ]

    outcome = reconcile_stage_b(
        [current_payment],
        [],
        [held],
        lines,
        [credit("held-only", held.id, utr="UTR-held-only", amount=8_764)],
    )[0]

    assert outcome.status is ResultStatus.missing_settlement
    assert outcome.autonomous is False
    assert any(
        item.rule_code == "HOLD_RELEASE" and item.result == "fail"
        for item in outcome.evidence
    )


def test_stage_a_exact_chain_with_close_runner_up_is_not_autonomous():
    exact_payment = payment("exact", business_at=NOW + timedelta(days=2))
    runner_up = payment(
        "runner",
        provider_order_id="order_runner",
        receipt="RCPT-0012",
    )

    outcome = reconcile_stage_a(
        [ledger()],
        [order()],
        [exact_payment, runner_up],
        [],
    )[0]

    assert outcome.status is ResultStatus.ambiguous
    assert outcome.autonomous is False


def test_engine_outcome_schema_serializes_without_truth_labels():
    outcome = reconcile_stage_a(*stage_a_case("exact_unique"))[0]
    serialized = EngineOutcomeSchema.model_validate(outcome).model_dump()

    assert serialized["status"] == "matched"
    assert "truth_case_id" not in str(serialized)
