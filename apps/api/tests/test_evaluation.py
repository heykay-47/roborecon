from app.evaluation.model import Prediction, TruthCase
from app.evaluation.service import evaluate_predictions


def _truth() -> list[TruthCase]:
    return [
        TruthCase(
            case_id="case-1",
            scenario_class="exact_id",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            source_ids=("ledger-1", "payment-1"),
        ),
        TruthCase(
            case_id="case-2",
            scenario_class="ambiguous",
            amount=2_000,
            matchable=True,
            expected_status="ambiguous",
            source_ids=("ledger-2",),
        ),
    ]


def test_false_positive_blocks_acceptance():
    predictions = [
        Prediction(
            case_id="case-1",
            status="matched",
            selected_ids=("ledger-1", "wrong-payment"),
            autonomous=True,
            amount=10_000,
            settlement_net=9_500,
        ),
        Prediction(
            case_id="case-2",
            status="ambiguous",
            selected_ids=("ledger-2",),
            autonomous=False,
            amount=2_000,
        ),
    ]

    report = evaluate_predictions(_truth(), predictions, duration_ms=100)

    assert report.precision < 100
    assert report.false_positives == 1
    assert report.acceptance_passed is False


def test_metrics_include_classes_review_closure_money_and_throughput():
    predictions = [
        Prediction(
            case_id="case-1",
            status="matched",
            selected_ids=("ledger-1", "payment-1"),
            autonomous=True,
            amount=10_000,
            settlement_net=9_500,
        ),
        Prediction(
            case_id="case-2",
            status="ambiguous",
            selected_ids=("ledger-2",),
            autonomous=False,
            amount=2_000,
            review_status="approved",
        ),
    ]

    report = evaluate_predictions(_truth(), predictions, duration_ms=100, source_count=20)

    assert set(report.per_class) == {"exact_id", "ambiguous"}
    assert report.match_rate == 100
    assert report.autonomous_resolution_rate == 50
    assert report.money_reconciled == 12_000
    assert report.money_unresolved == 0
    assert report.settlement_net == 9_500
    assert report.throughput == 200.0
    assert report.review_adjusted["closedCases"] == 2


def test_unscored_batch_reports_benchmark_unavailable():
    report = evaluate_predictions([], [], duration_ms=100, benchmark_available=False)

    assert report.benchmark_available is False
    assert report.acceptance_passed is False
