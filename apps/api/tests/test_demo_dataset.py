from app.common.money import calculate_fee, calculate_gst
from app.demo.dataset import build_demo_dataset


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
    custom = build_demo_dataset("razorrecon-v2")

    assert custom == build_demo_dataset("razorrecon-v2")
    assert default.batch_id != custom.batch_id
    assert default.ledger_entries[0].id != custom.ledger_entries[0].id
    assert default.razorpay_payments[0].id != custom.razorpay_payments[0].id
