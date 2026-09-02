from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from benchmark import fixed_predictions, fixed_truth

from app.batch.model import Batch
from app.common.enums import (
    BatchKind,
    BatchStatus,
    ExceptionStatus,
    ReconciliationStage,
    ResultStatus,
    RunStatus,
)
from app.evaluation.model import Prediction, TruthCase, TruthSource
from app.evaluation.service import evaluate_predictions, evaluate_run
from app.reconciliation.model import MatchLink, ReconciliationResult, ReconciliationRun


def source(source_type: str, source_id: str) -> TruthSource:
    return TruthSource(source_type=source_type, source_id=source_id)


def matched_truth(case_id: str = "case-1", scenario_class: str = "standard") -> TruthCase:
    return TruthCase(
        case_id=case_id,
        scenario_class=scenario_class,
        amount=10_000,
        matchable=True,
        expected_status="matched",
        sources=(
            source("ledger", f"ledger-{case_id}"),
            source("razorpay_order", f"order-{case_id}"),
            source("razorpay_payment", f"payment-{case_id}"),
            source("settlement", f"settlement-{case_id}"),
            source("bank_credit", f"bank-{case_id}"),
        ),
    )


def _truth() -> list[TruthCase]:
    return [
        matched_truth("case-1", "exact_id"),
        TruthCase(
            case_id="case-2",
            scenario_class="ambiguous",
            amount=2_000,
            matchable=False,
            expected_status="ambiguous",
            sources=(source("ledger", "ledger-2"),),
        ),
    ]


def test_false_positive_blocks_acceptance():
    predictions = [
        Prediction(
            case_id="case-1",
            status="matched",
            selected_ids=("ledger-case-1", "wrong-payment"),
            autonomous=True,
            amount=10_000,
            settlement_net=9_500,
            stage="ledger_to_razorpay",
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
            selected_ids=("ledger-case-1", "order-case-1", "payment-case-1"),
            autonomous=True,
            amount=10_000,
            settlement_net=9_500,
            stage="ledger_to_razorpay",
        ),
        Prediction(
            case_id="case-1",
            status="matched",
            selected_ids=("payment-case-1", "settlement-case-1", "bank-case-1"),
            autonomous=True,
            amount=10_000,
            settlement_net=9_500,
            stage="razorpay_to_settlement",
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
    assert report.end_to_end_autonomy_rate == 100
    assert report.money_reconciled == 10_000
    assert report.money_unresolved == 2_000
    assert report.financially_unresolved_cases == 0
    assert report.settlement_net == 9_500
    assert report.throughput == 200.0
    assert report.review_adjusted["closedCases"] == 2


def test_unscored_batch_reports_benchmark_unavailable():
    report = evaluate_predictions(
        [],
        [
            Prediction(
                case_id=None,
                status="matched",
                selected_ids=("settlement-1",),
                autonomous=True,
                settlement_net=9_500,
            ),
            Prediction(
                case_id=None,
                status="ambiguous",
                autonomous=False,
            ),
        ],
        duration_ms=100,
        source_count=20,
        benchmark_available=False,
        open_exception_count=1,
    )

    assert report.benchmark_available is False
    assert report.precision is None
    assert report.false_positives is None
    assert report.match_rate is None
    assert report.end_to_end_autonomy_rate is None
    assert report.exception_recall is None
    assert report.per_class is None
    assert report.stage_metrics is None
    assert report.records_processed == 20
    assert report.duration_ms == 100
    assert report.throughput == 200.0
    assert report.open_exceptions == 1
    assert report.settlement_net == 9_500
    assert report.acceptance_passed is False


def test_matched_case_requires_both_stages_and_complete_source_coverage():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
                source("settlement", "settlement-1"),
                source("bank_credit", "bank-1"),
            ),
        )
    ]

    partial_report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            ),
            Prediction(
                case_id="case-1",
                status="missing_settlement",
                selected_ids=("payment-1",),
                stage="razorpay_to_settlement",
            ),
        ],
        duration_ms=100,
    )

    assert partial_report.match_rate == 0
    assert partial_report.autonomous_cases == 0
    assert partial_report.financially_unresolved_cases == 1
    assert partial_report.stage_metrics["ledger_to_razorpay"].correctness_rate == 100
    assert partial_report.stage_metrics["razorpay_to_settlement"].correctness_rate == 0
    assert partial_report.stage_metrics["razorpay_to_settlement"].unresolved_cases == 1

    complete_report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            ),
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("payment-1", "settlement-1", "bank-1"),
                autonomous=True,
                stage="razorpay_to_settlement",
            ),
        ],
        duration_ms=100,
    )

    assert complete_report.match_rate == 100
    assert complete_report.autonomous_cases == 1
    assert complete_report.financially_unresolved_cases == 0


def test_matched_case_with_missing_stage_metadata_is_not_complete():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
                source("settlement", "settlement-1"),
                source("bank_credit", "bank-1"),
            ),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1", "settlement-1", "bank-1"),
                autonomous=True,
            )
        ],
        duration_ms=100,
    )

    assert report.match_rate == 0
    assert report.autonomous_cases == 0
    assert report.financially_unresolved_cases == 1
    assert report.money_reconciled == 0
    assert report.money_unresolved == 10_000


def test_matched_case_with_unknown_stage_metadata_is_not_complete():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
                source("settlement", "settlement-1"),
                source("bank_credit", "bank-1"),
            ),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1", "settlement-1", "bank-1"),
                autonomous=True,
                stage="unknown",
            )
        ],
        duration_ms=100,
    )

    assert report.match_rate == 0
    assert report.autonomous_cases == 0
    assert report.financially_unresolved_cases == 1


def test_matched_case_with_one_non_autonomous_stage_is_not_autonomous():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
                source("settlement", "settlement-1"),
                source("bank_credit", "bank-1"),
            ),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            ),
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("payment-1", "settlement-1", "bank-1"),
                autonomous=False,
                stage="razorpay_to_settlement",
            ),
        ],
        duration_ms=100,
    )

    assert report.match_rate == 100
    assert report.autonomous_cases == 0
    assert report.financially_unresolved_cases == 1
    assert report.money_reconciled == 0
    assert report.money_unresolved == 10_000


@pytest.mark.parametrize("extra_stage", [None, "unknown"])
def test_matched_case_with_extra_unknown_or_missing_stage_is_not_resolved(extra_stage):
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
                source("settlement", "settlement-1"),
                source("bank_credit", "bank-1"),
            ),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            ),
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("payment-1", "settlement-1", "bank-1"),
                autonomous=True,
                stage="razorpay_to_settlement",
            ),
            Prediction(
                case_id="case-1",
                status="matched",
                autonomous=True,
                stage=extra_stage,
            ),
        ],
        duration_ms=100,
    )

    assert report.correctly_resolved == 0
    assert report.match_rate == 0
    assert report.autonomous_cases == 0
    assert report.financially_unresolved_cases == 1
    assert report.money_reconciled == 0
    assert report.money_unresolved == 10_000


def test_exception_case_is_correct_but_never_financially_or_autonomously_resolved():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="amount_mismatch",
            amount=10_000,
            matchable=False,
            expected_status="amount_mismatch",
            sources=(source("ledger", "ledger-1"),),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="amount_mismatch",
                selected_ids=("ledger-1",),
                autonomous=True,
            )
        ],
        duration_ms=100,
    )

    assert report.correctly_resolved == 0
    assert report.precision == 100
    assert report.autonomous_cases == 0
    assert report.exception_recall == 0
    assert report.financially_unresolved_cases == 0
    assert report.money_reconciled == 0
    assert report.money_unresolved == 10_000


def test_precision_uses_autonomous_selected_link_count_for_class_and_stage_metrics():
    truth = [
        TruthCase(
            case_id="case-1",
            scenario_class="standard",
            amount=10_000,
            matchable=True,
            expected_status="matched",
            sources=(
                source("ledger", "ledger-1"),
                source("razorpay_payment", "payment-1"),
            ),
        )
    ]

    report = evaluate_predictions(
        truth,
        [
            Prediction(
                case_id="case-1",
                status="matched",
                selected_ids=("ledger-1", "payment-1", "wrong-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            )
        ],
        duration_ms=100,
    )

    assert report.precision == 66.67
    assert report.false_positives == 1
    assert report.per_class["standard"].precision == 66.67
    assert report.per_class["standard"].false_positives == 1
    assert report.stage_metrics["ledger_to_razorpay"].autonomous_links == 3
    assert report.stage_metrics["ledger_to_razorpay"].precision == 66.67
    assert report.stage_metrics["ledger_to_razorpay"].open_exceptions == 0


def test_strict_stage_and_end_to_end_metrics_are_separate():
    case = matched_truth()
    report = evaluate_predictions(
        [case],
        [
            Prediction(
                case_id=case.case_id,
                status="matched",
                selected_ids=("ledger-case-1", "order-case-1", "payment-case-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
            ),
            Prediction(
                case_id=case.case_id,
                status="matched",
                selected_ids=("payment-case-1", "settlement-case-1", "bank-case-1"),
                autonomous=False,
                stage="razorpay_to_settlement",
            ),
        ],
        duration_ms=100,
    )

    assert report.stage_metrics["ledger_to_razorpay"].autonomy_rate == 100
    assert report.stage_metrics["razorpay_to_settlement"].autonomy_rate == 0
    assert report.match_rate == 100
    assert report.end_to_end_autonomy_rate == 0


@pytest.mark.parametrize("review_status", ["approved", "rejected"])
def test_reviewed_required_stage_is_not_end_to_end_autonomous(review_status):
    case = matched_truth()
    report = evaluate_predictions(
        [case],
        [
            Prediction(
                case_id=case.case_id,
                status="matched",
                selected_ids=("ledger-case-1", "order-case-1", "payment-case-1"),
                autonomous=True,
                stage="ledger_to_razorpay",
                review_status=review_status,
            ),
            Prediction(
                case_id=case.case_id,
                status="matched",
                selected_ids=("payment-case-1", "settlement-case-1", "bank-case-1"),
                autonomous=True,
                stage="razorpay_to_settlement",
            ),
        ],
        duration_ms=100,
    )

    assert report.match_rate == 100
    assert report.end_to_end_autonomy_rate == 0
    assert report.autonomous_cases == 0


def test_exception_recall_requires_expected_non_autonomous_status():
    case = TruthCase(
        case_id="exception-1",
        scenario_class="missing_settlement",
        amount=10_000,
        matchable=False,
        expected_status="missing_settlement",
        sources=(
            source("ledger", "ledger-1"),
            source("razorpay_payment", "payment-1"),
        ),
    )
    expected = Prediction(
        case_id=case.case_id,
        status="missing_settlement",
        selected_ids=("payment-1",),
        autonomous=False,
        stage="razorpay_to_settlement",
    )

    assert evaluate_predictions([case], [expected], duration_ms=100).exception_recall == 100
    assert evaluate_predictions([case], [], duration_ms=100).exception_recall == 0


def test_unmatched_autonomous_stage_prediction_is_a_false_positive():
    report = evaluate_predictions(
        [],
        [
            Prediction(
                case_id="unknown-case",
                status="matched",
                selected_ids=("unknown-source",),
                autonomous=True,
                stage="ledger_to_razorpay",
            )
        ],
        duration_ms=100,
    )

    assert report.false_positives == 1
    assert report.precision == 0


def test_fixed_benchmark_reports_bounded_source_data_errors():
    from app.demo.dataset import build_demo_dataset

    dataset = build_demo_dataset()
    report = evaluate_predictions(
        fixed_truth(dataset),
        fixed_predictions(dataset),
        duration_ms=100,
        source_count=dataset.source_row_count,
    )

    assert report.precision == 98.55
    assert report.false_positives == 8
    assert report.match_rate == 94.74
    assert report.end_to_end_autonomy_rate == 94.74
    assert report.correctly_resolved == 72
    assert report.autonomous_cases == 72
    assert report.stage_metrics["ledger_to_razorpay"].autonomy_rate == 94.74
    assert report.stage_metrics["ledger_to_razorpay"].precision == 96.49
    assert report.stage_metrics["razorpay_to_settlement"].autonomy_rate == 100
    assert report.exception_recall == 100
    assert all(report.acceptance_checks.values())
    assert report.acceptance_passed is True


@pytest.mark.asyncio
async def test_evaluate_run_uses_persisted_results_and_hidden_truth_after_completion():
    batch_id = uuid4()
    run_id = uuid4()
    positive_case_id = uuid4()
    exception_case_id = uuid4()
    ledger_id = uuid4()
    order_id = uuid4()
    payment_id = uuid4()
    refund_id = uuid4()
    settlement_id = uuid4()
    bank_credit_id = uuid4()
    exception_payment_id = uuid4()
    run = ReconciliationRun(
        id=run_id,
        batch_id=batch_id,
        status=RunStatus.completed,
        started_at=SimpleNamespace(),
        duration_ms=100,
        source_row_count=4,
    )
    batch = Batch(
        id=batch_id,
        kind=BatchKind.demo,
        status=BatchStatus.completed,
        ground_truth_available=True,
    )
    first_result = ReconciliationResult(
        id=uuid4(),
        run_id=run_id,
        batch_id=batch_id,
        stage=ReconciliationStage.ledger_to_razorpay,
        status=ResultStatus.matched,
        primary_source_type="ledger",
        primary_source_id=ledger_id,
        amount=10_000,
        currency="INR",
        autonomous=True,
        selected_ids=[str(refund_id)],
    )
    second_result = ReconciliationResult(
        id=uuid4(),
        run_id=run_id,
        batch_id=batch_id,
        stage=ReconciliationStage.razorpay_to_settlement,
        status=ResultStatus.matched,
        primary_source_type="razorpay_payment",
        primary_source_id=payment_id,
        amount=10_000,
        currency="INR",
        autonomous=True,
        selected_ids=[str(refund_id), str(settlement_id), str(bank_credit_id)],
    )
    exception_result = ReconciliationResult(
        id=uuid4(),
        run_id=run_id,
        batch_id=batch_id,
        stage=ReconciliationStage.razorpay_to_settlement,
        status=ResultStatus.missing_settlement,
        primary_source_type="razorpay_payment",
        primary_source_id=exception_payment_id,
        amount=1_000,
        currency="INR",
        autonomous=False,
        selected_ids=[],
    )
    links = [
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=first_result.id,
            source_type="ledger",
            source_id=ledger_id,
            role="primary",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=first_result.id,
            source_type="razorpay_refund",
            source_id=refund_id,
            role="selected",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=second_result.id,
            source_type="razorpay_payment",
            source_id=payment_id,
            role="primary",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=first_result.id,
            source_type="razorpay_order",
            source_id=order_id,
            role="related",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=second_result.id,
            source_type="razorpay_refund",
            source_id=refund_id,
            role="selected",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=second_result.id,
            source_type="settlement",
            source_id=settlement_id,
            role="selected",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=second_result.id,
            source_type="bank_credit",
            source_id=bank_credit_id,
            role="selected",
            autonomous=True,
            actor="system",
        ),
    ]
    positive_case = SimpleNamespace(
        id=positive_case_id,
        scenario_class="standard",
        amount=10_000,
        matchable=True,
        expected_status=ResultStatus.matched,
    )
    exception_case = SimpleNamespace(
        id=exception_case_id,
        scenario_class="missing_settlement",
        amount=1_000,
        matchable=False,
        expected_status=ResultStatus.missing_settlement,
    )
    truth_links = [
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="ledger",
            source_id=ledger_id,
        ),
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="razorpay_order",
            source_id=order_id,
        ),
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="razorpay_payment",
            source_id=payment_id,
        ),
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="razorpay_refund",
            source_id=refund_id,
        ),
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="settlement",
            source_id=settlement_id,
        ),
        SimpleNamespace(
            evaluation_case_id=positive_case_id,
            source_type="bank_credit",
            source_id=bank_credit_id,
        ),
        SimpleNamespace(
            evaluation_case_id=exception_case_id,
            source_type="razorpay_payment",
            source_id=exception_payment_id,
        ),
    ]

    stage_a_link_ids = {
        link.source_id for link in links if link.result_id == first_result.id
    }
    stage_b_link_ids = {
        link.source_id for link in links if link.result_id == second_result.id
    }
    assert stage_a_link_ids == {ledger_id, order_id, refund_id}
    assert stage_b_link_ids == {payment_id, refund_id, settlement_id, bank_credit_id}

    def rows(values):
        result = MagicMock()
        result.scalars.return_value.all.return_value = values
        return result

    session = AsyncMock()
    session.get = AsyncMock(side_effect=[run, batch])
    session.execute = AsyncMock(
        side_effect=[
            rows([first_result, second_result, exception_result]),
            rows(links),
            rows(
                [
                    SimpleNamespace(
                        result_id=exception_result.id,
                        status=ExceptionStatus.open,
                    )
                ]
            ),
            rows([SimpleNamespace(id=settlement_id, amount=9_500)]),
            rows([positive_case, exception_case]),
            rows(truth_links),
        ]
    )
    session.commit = AsyncMock()

    report = await evaluate_run(session, run_id)

    assert report.match_rate == 100
    assert report.end_to_end_autonomy_rate == 100
    assert report.exception_recall == 100
    assert report.stage_metrics["ledger_to_razorpay"].correctness_rate == 100
    assert report.stage_metrics["razorpay_to_settlement"].correctness_rate == 100
    assert all(report.acceptance_checks.values())
    assert report.acceptance_passed is True
    assert report.settlement_net == 9_500
    assert run.metrics is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_run_preserves_raw_selected_ids_in_addition_to_match_links():
    batch_id = uuid4()
    run_id = uuid4()
    case_id = uuid4()
    ledger_id = uuid4()
    payment_id = uuid4()
    unexpected_id = uuid4()
    result = ReconciliationResult(
        id=uuid4(),
        run_id=run_id,
        batch_id=batch_id,
        stage=ReconciliationStage.ledger_to_razorpay,
        status=ResultStatus.matched,
        primary_source_type="ledger",
        primary_source_id=ledger_id,
        amount=10_000,
        currency="INR",
        autonomous=True,
        selected_ids=[str(payment_id), str(unexpected_id)],
    )
    run = ReconciliationRun(
        id=run_id,
        batch_id=batch_id,
        status=RunStatus.completed,
        started_at=SimpleNamespace(),
        duration_ms=100,
        source_row_count=3,
    )
    batch = Batch(
        id=batch_id,
        kind=BatchKind.demo,
        status=BatchStatus.completed,
        ground_truth_available=True,
    )
    case = SimpleNamespace(
        id=case_id,
        scenario_class="standard",
        amount=10_000,
        matchable=True,
        expected_status=ResultStatus.matched,
    )
    links = [
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=result.id,
            source_type="ledger",
            source_id=ledger_id,
            role="primary",
            autonomous=True,
            actor="system",
        ),
        MatchLink(
            id=uuid4(),
            run_id=run_id,
            result_id=result.id,
            source_type="razorpay_payment",
            source_id=payment_id,
            role="selected",
            autonomous=True,
            actor="system",
        ),
    ]
    truth_links = [
        SimpleNamespace(
            evaluation_case_id=case_id,
            source_type="ledger",
            source_id=ledger_id,
        ),
        SimpleNamespace(
            evaluation_case_id=case_id,
            source_type="razorpay_payment",
            source_id=payment_id,
        ),
    ]

    def rows(values):
        result = MagicMock()
        result.scalars.return_value.all.return_value = values
        return result

    session = AsyncMock()
    session.get = AsyncMock(side_effect=[run, batch])
    session.execute = AsyncMock(
        side_effect=[
            rows([result]),
            rows(links),
            rows([]),
            rows([]),
            rows([case]),
            rows(truth_links),
        ]
    )
    session.commit = AsyncMock()

    report = await evaluate_run(session, run_id)

    assert report.false_positives == 1
    assert report.precision == 66.67
