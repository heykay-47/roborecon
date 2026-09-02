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
