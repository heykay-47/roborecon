from collections import Counter

from app.common.enums import ResultStatus
from app.common.money import calculate_fee, calculate_gst
from app.demo.dataset import build_demo_dataset

EXPECTED_PRIMARY_CLASSES = {
    "standard": 20,
    "exact_id": 6,
    "fuzzy_reference": 14,
    "date_shift": 10,
    "fee_gst": 10,
    "refund": 10,
    "held_release": 6,
    "duplicate": 8,
    "ambiguous": 8,
    "amount_mismatch": 8,
    "missing_razorpay": 8,
    "missing_settlement": 6,
    "missing_bank_credit": 6,
    "missing_ledger": 6,
}


def test_strict_benchmark_truth_contract():
    dataset = build_demo_dataset()

    assert Counter(case.scenario_class for case in dataset.truth_cases) == (
        EXPECTED_PRIMARY_CLASSES
    )
    assert len(dataset.truth_cases) == 126
    assert sum(case.matchable for case in dataset.truth_cases) == 76
    assert sum(not case.matchable for case in dataset.truth_cases) == 50
    assert all(
        case.matchable is (case.expected_status is ResultStatus.matched)
        for case in dataset.truth_cases
    )

    expected_exceptions = {
        ResultStatus.duplicate: 8,
        ResultStatus.ambiguous: 8,
        ResultStatus.amount_mismatch: 8,
        ResultStatus.missing_razorpay: 8,
        ResultStatus.missing_settlement: 6,
        ResultStatus.missing_bank_credit: 6,
        ResultStatus.missing_ledger: 6,
    }
    assert Counter(
        case.expected_status
        for case in dataset.truth_cases
        if not case.matchable
    ) == expected_exceptions


def test_positive_cases_have_source_visible_identity_evidence():
    dataset = build_demo_dataset()
    ledger_by_id = {row.id: row for row in dataset.ledger_entries}
    payment_by_id = {row.id: row for row in dataset.razorpay_payments}
    order_by_id = {row.id: row for row in dataset.razorpay_orders}

    adversarial_case_ids = {
        dataset.truth_cases[index].case_id for index in (9, 10, 20, 108)
    }
    for case in dataset.truth_cases:
        if not case.matchable:
            continue
        ledger = ledger_by_id[case.ledger_entry_id]
        payment = payment_by_id[case.razorpay_payment_id]
        order = order_by_id[case.razorpay_order_id]

        assert payment.provider_order_id == order.provider_order_id
        assert payment.amount == order.amount
        assert payment.currency == order.currency == ledger.currency
        assert order.status == "paid"
        if case.case_id in adversarial_case_ids:
            assert ledger.reference != payment.receipt
            assert ledger.reference.startswith("pay_")
        elif case.scenario_class == "fuzzy_reference":
            assert ledger.reference != payment.receipt
            assert "INVOICE" in ledger.reference.upper()
            assert "INVOICE" in payment.receipt.upper()
        else:
            assert ledger.reference == payment.receipt == order.receipt


def test_adversarial_reference_pairs_cross_equal_amount_payments():
    dataset = build_demo_dataset()
    ledger_by_id = {row.id: row for row in dataset.ledger_entries}
    payment_by_id = {row.id: row for row in dataset.razorpay_payments}

    for left_index, right_index in ((9, 10), (20, 108)):
        left = dataset.truth_cases[left_index]
        right = dataset.truth_cases[right_index]
        left_ledger = ledger_by_id[left.ledger_entry_id]
        right_ledger = ledger_by_id[right.ledger_entry_id]
        left_payment = payment_by_id[left.razorpay_payment_id]
        right_payment = payment_by_id[right.razorpay_payment_id]

        assert left.amount == right.amount
        assert left_ledger.reference == right_payment.provider_payment_id
        assert right_ledger.reference == left_payment.provider_payment_id
        assert left.razorpay_payment_id != right.razorpay_payment_id


def test_fixed_dataset_contract():
    first = build_demo_dataset()
    second = build_demo_dataset()

    assert first == second
    assert len(first.ledger_entries) == 120
    assert len(first.provider_only_cases) == 6
    assert len(first.malformed_rows) == 6
    assert 350 <= first.source_row_count <= 450
    assert first.scenario_counts["exact_id"] >= 32
    assert first.scenario_counts["held_release"] >= 6
    assert first.truth_cases[80].expected_status.value == "missing_razorpay"
    assert first.provider_only_cases[0].expected_status.value == "missing_ledger"


def test_dataset_source_records_do_not_expose_truth_links():
    dataset = build_demo_dataset()

    assert all(not hasattr(record, "truth_case_id") for record in dataset.ledger_entries)
    assert all(not hasattr(record, "truth_case_id") for record in dataset.razorpay_orders)
    assert all(not hasattr(record, "truth_case_id") for record in dataset.razorpay_payments)
    assert all(not hasattr(record, "truth_case_id") for record in dataset.settlements)


def test_money_arithmetic_uses_integer_paise_and_half_up_rounding():
    assert calculate_fee(10_001) == 200
    assert calculate_fee(10_000) == 200
    assert calculate_gst(201) == 36


def test_provider_present_cases_have_scenario_consistent_settlements():
    dataset = build_demo_dataset()
    settlement_ids = {settlement.id for settlement in dataset.settlements}
    bank_credit_ids = {credit.id for credit in dataset.bank_credits}
    lines_by_settlement: dict = {}
    for line in dataset.settlement_lines:
        lines_by_settlement.setdefault(line.settlement_id, []).append(line)

    for case in dataset.truth_cases:
        if case.ledger_entry_id is None or case.razorpay_payment_id is None:
            continue
        if "missing_settlement" in case.scenario_tags:
            assert case.settlement_ids == ()
            continue

        assert case.settlement_ids
        assert set(case.settlement_ids) <= settlement_ids
        assert all(
            lines_by_settlement.get(settlement_id)
            for settlement_id in case.settlement_ids
        )
        if "missing_bank_credit" in case.scenario_tags:
            assert case.bank_credit_ids == ()
        else:
            assert set(case.bank_credit_ids) <= bank_credit_ids
            assert len(case.bank_credit_ids) == len(case.settlement_ids)


def test_missing_bank_and_missing_settlement_are_independent_scenarios():
    dataset = build_demo_dataset()
    missing_bank = [
        case for case in dataset.truth_cases if "missing_bank_credit" in case.scenario_tags
    ]

    assert len(missing_bank) == 6
    assert all("missing_settlement" not in case.scenario_tags for case in missing_bank)
    assert all(case.settlement_ids and not case.bank_credit_ids for case in missing_bank)


def test_held_release_truth_includes_release_settlement_and_bank_credit():
    dataset = build_demo_dataset()
    held_cases = [case for case in dataset.truth_cases if "held_release" in case.scenario_tags]

    assert len(held_cases) == 6
    assert all(len(case.settlement_ids) == 2 for case in held_cases)
    assert all(len(case.bank_credit_ids) == 2 for case in held_cases)
    assert all(case.bank_credit_id in case.bank_credit_ids for case in held_cases)


def test_fee_gst_cases_have_fee_and_tax_settlement_lines():
    dataset = build_demo_dataset()
    lines_by_settlement: dict = {}
    for line in dataset.settlement_lines:
        lines_by_settlement.setdefault(line.settlement_id, []).append(line)

    fee_cases = [case for case in dataset.truth_cases if "fee_gst" in case.scenario_tags]
    assert len(fee_cases) == 24
    assert all(
        {
            line.line_type.value
            for settlement_id in case.settlement_ids
            for line in lines_by_settlement[settlement_id]
        }
        >= {"fee", "tax"}
        for case in fee_cases
    )


def test_custom_seed_changes_stable_source_ids():
    default = build_demo_dataset()
    custom = build_demo_dataset("roborecon-v2")

    assert custom == build_demo_dataset("roborecon-v2")
    assert default.batch_id != custom.batch_id
    assert default.ledger_entries[0].id != custom.ledger_entries[0].id
    assert default.razorpay_payments[0].id != custom.razorpay_payments[0].id
