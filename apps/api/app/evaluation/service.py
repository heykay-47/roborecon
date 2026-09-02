from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import Batch
from app.common.enums import ExceptionStatus, RunStatus
from app.evaluation.model import (
    EVALUATION_REPORT_VERSION,
    ClassMetrics,
    EvaluationCase,
    EvaluationReport,
    GroundTruthLink,
    Prediction,
    StageMetrics,
    TruthCase,
    TruthSource,
)
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import Settlement

MATCH_RATE_TARGET = 90.0
PRECISION_TARGET = 98.0
FALSE_POSITIVE_LIMIT = 8
END_TO_END_AUTONOMY_TARGET = 90.0
STAGE_CORRECTNESS_TARGET = 90.0
CLASS_ACCURACY_TARGET = 90.0
EXCEPTION_RECALL_TARGET = 100.0
RUNTIME_LIMIT_MS = 5_000

ACCEPTANCE_CHECK_KEYS = (
    "benchmarkAvailable",
    "precision",
    "falsePositives",
    "matchRate",
    "endToEndAutonomy",
    "stageACorrectness",
    "stageBCorrectness",
    "positiveClassAccuracy",
    "exceptionRecall",
    "runtime",
)


def _value(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _string(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _ids(value: Any) -> tuple[str, ...]:
    raw = _value(
        value,
        "source_ids",
        "selected_ids",
        "selected_source_ids",
        "links",
        "ground_truth_links",
        default=(),
    )
    if raw is None:
        return ()
    if isinstance(raw, (str, UUID)):
        return (str(raw),)
    if isinstance(raw, Mapping):
        raw = raw.values()
    result: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("source_id", item.get("id"))
        elif hasattr(item, "source_id"):
            item = item.source_id
        if item is not None:
            result.append(str(item))
    return tuple(dict.fromkeys(result))


def _truth_sources(value: Any) -> tuple[TruthSource, ...]:
    raw_sources = _value(value, "sources", "ground_truth_links", default=()) or ()
    sources = []
    for item in raw_sources:
        source_type = _value(item, "source_type", "sourceType")
        source_id = _value(item, "source_id", "sourceId", "id")
        if source_type is not None and source_id is not None:
            sources.append(
                TruthSource(source_type=str(source_type), source_id=str(source_id))
            )
    return tuple(dict.fromkeys(sources))


def _truth_case(value: TruthCase | Mapping[str, Any] | Any, key: Any = None) -> TruthCase:
    case_id = _value(value, "case_id", "id", default=key)
    return TruthCase(
        case_id=str(case_id),
        scenario_class=str(
            _value(value, "scenario_class", "scenarioClass", default="unknown")
        ),
        amount=int(_value(value, "amount", default=0) or 0),
        matchable=bool(_value(value, "matchable", default=True)),
        expected_status=_string(
            _value(value, "expected_status", "expectedStatus", default="matched")
        ),
        sources=_truth_sources(value),
    )


def _truth_cases(values: Iterable[Any] | Mapping[Any, Any]) -> list[TruthCase]:
    if isinstance(values, Mapping):
        return [_truth_case(value, key) for key, value in values.items()]
    return [_truth_case(value) for value in values]


def _prediction(value: Prediction | Mapping[str, Any] | Any) -> Prediction:
    return Prediction(
        case_id=(
            str(case_id)
            if (case_id := _value(value, "case_id", "caseId")) is not None
            else None
        ),
        status=_string(_value(value, "status", default="matched")),
        selected_ids=_ids(value),
        autonomous=bool(_value(value, "autonomous", default=False)),
        amount=(
            int(amount)
            if (amount := _value(value, "amount", default=None)) is not None
            else None
        ),
        settlement_net=(
            int(net)
            if (net := _value(value, "settlement_net", "settlementNet", default=None))
            is not None
            else None
        ),
        stage=(
            _string(stage)
            if (stage := _value(value, "stage", default=None)) is not None
            else None
        ),
        review_status=(
            _string(review_status)
            if (
                review_status := _value(
                    value, "review_status", "reviewStatus", default=None
                )
            )
            is not None
            else None
        ),
    )


def _predictions(values: Iterable[Any] | Mapping[Any, Any]) -> list[Prediction]:
    if isinstance(values, Mapping):
        result = []
        for case_id, value in values.items():
            prediction = _prediction(value)
            if prediction.case_id is None:
                prediction = Prediction(
                    case_id=str(case_id),
                    status=prediction.status,
                    selected_ids=prediction.selected_ids,
                    autonomous=prediction.autonomous,
                    amount=prediction.amount,
                    settlement_net=prediction.settlement_net,
                    stage=prediction.stage,
                    review_status=prediction.review_status,
                )
            result.append(prediction)
        return result
    return [_prediction(value) for value in values]


def _associate_predictions(
    truth: list[TruthCase], predictions: list[Prediction]
) -> list[Prediction]:
    truth_by_id = {case.case_id: case for case in truth}
    result: list[Prediction] = []
    for prediction in predictions:
        if prediction.case_id in truth_by_id or not prediction.selected_ids:
            result.append(prediction)
            continue
        predicted_ids = set(prediction.selected_ids)
        overlaps = [
            (len(predicted_ids.intersection(case.source_ids)), case)
            for case in truth
        ]
        overlaps = [item for item in overlaps if item[0] > 0]
        if not overlaps:
            result.append(prediction)
            continue
        overlaps.sort(key=lambda item: (-item[0], item[1].case_id))
        best_count, best_case = overlaps[0]
        if len(overlaps) == 1 or best_count > overlaps[1][0]:
            result.append(
                Prediction(
                    case_id=best_case.case_id,
                    status=prediction.status,
                    selected_ids=prediction.selected_ids,
                    autonomous=prediction.autonomous,
                    amount=prediction.amount,
                    settlement_net=prediction.settlement_net,
                    stage=prediction.stage,
                    review_status=prediction.review_status,
                )
            )
        else:
            result.append(prediction)
    return result


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100 / denominator, 2)


_REQUIRED_STAGES = {
    "ledger_to_razorpay",
    "razorpay_to_settlement",
}
_REQUIRED_STAGE_ORDER = (
    "ledger_to_razorpay",
    "razorpay_to_settlement",
)


def _case_status_correct(case: TruthCase, predictions: list[Prediction]) -> bool:
    if not predictions:
        return False
    statuses = {_string(prediction.status) for prediction in predictions}
    if case.expected_status != "matched":
        return case.expected_status in statuses
    if statuses != {"matched"}:
        return False
    if any(
        prediction.stage is None
        or _string(prediction.stage) not in _REQUIRED_STAGES
        for prediction in predictions
    ):
        return False
    stages = {_string(prediction.stage) for prediction in predictions}
    return stages == _REQUIRED_STAGES


def _case_source_coverage(case: TruthCase, predictions: list[Prediction]) -> bool:
    expected_ids = set(case.source_ids)
    selected_ids = {
        source_id for prediction in predictions for source_id in prediction.selected_ids
    }
    return expected_ids.issubset(selected_ids) and selected_ids.issubset(expected_ids)


def _case_has_selected_false_positive(
    case: TruthCase, predictions: list[Prediction]
) -> bool:
    expected_ids = set(case.source_ids)
    return any(
        set(prediction.selected_ids).difference(expected_ids)
        for prediction in predictions
    )


def _case_is_correct(case: TruthCase, predictions: list[Prediction]) -> bool:
    if not _case_status_correct(case, predictions):
        return False
    if case.expected_status != "matched":
        return True
    if _case_has_selected_false_positive(case, predictions):
        return False
    return _case_source_coverage(case, predictions)


def _case_is_autonomously_resolved(
    case: TruthCase, predictions: list[Prediction]
) -> bool:
    return (
        case.expected_status == "matched"
        and _case_is_correct(case, predictions)
        and bool(predictions)
        and all(
            prediction.autonomous and prediction.review_status is None
            for prediction in predictions
        )
    )


def _case_is_financially_resolved(
    case: TruthCase, predictions: list[Prediction]
) -> bool:
    if case.expected_status != "matched" or not _case_is_correct(case, predictions):
        return False
    return bool(predictions) and all(
        prediction.autonomous or prediction.review_status == "approved"
        for prediction in predictions
    )


def _autonomous_false_positive_count(
    case: TruthCase | None, prediction: Prediction
) -> int:
    if not prediction.autonomous:
        return 0
    selected_ids = set(prediction.selected_ids)
    if case is None:
        return len(selected_ids) or 1
    return len(selected_ids.difference(case.source_ids)) or int(not selected_ids)


def _expected_stage_ids(case: TruthCase, stage: str) -> set[str]:
    by_type: dict[str, set[str]] = defaultdict(set)
    for source in case.sources:
        by_type[source.source_type].add(source.source_id)
    if stage == "ledger_to_razorpay":
        provider_ids = by_type["razorpay_refund"] or by_type["razorpay_payment"]
        return by_type["ledger"] | by_type["razorpay_order"] | provider_ids
    if stage == "razorpay_to_settlement":
        return (
            by_type["razorpay_payment"]
            | by_type["razorpay_refund"]
            | by_type["settlement"]
            | by_type["bank_credit"]
        )
    return set()


def _stage_case_is_correct(
    case: TruthCase, predictions: list[Prediction], stage: str
) -> bool:
    if not predictions:
        return False
    if case.expected_status != "matched":
        return False
    if any(_string(prediction.status) != "matched" for prediction in predictions):
        return False
    selected_ids = {
        source_id for prediction in predictions for source_id in prediction.selected_ids
    }
    return selected_ids == _expected_stage_ids(case, stage)


def _stage_case_is_autonomous(
    case: TruthCase, predictions: list[Prediction], stage: str
) -> bool:
    return _stage_case_is_correct(case, predictions, stage) and all(
        prediction.autonomous for prediction in predictions
    )


def _autonomous_stage_false_positive_count(
    case: TruthCase | None, prediction: Prediction, stage: str
) -> int:
    if not prediction.autonomous:
        return 0
    selected_ids = set(prediction.selected_ids)
    expected_ids = _expected_stage_ids(case, stage) if case is not None else set()
    return len(selected_ids.difference(expected_ids)) or int(not selected_ids)


def _exception_is_recalled(case: TruthCase, predictions: list[Prediction]) -> bool:
    return not case.matchable and any(
        not prediction.autonomous
        and _string(prediction.status) == case.expected_status
        for prediction in predictions
    )


def _acceptance_checks(
    *,
    benchmark_available: bool,
    precision: float | None,
    false_positives: int | None,
    match_rate: float | None,
    end_to_end_autonomy_rate: float | None,
    stage_a: StageMetrics | None,
    stage_b: StageMetrics | None,
    per_class: dict[str, ClassMetrics] | None,
    exception_recall: float | None,
    duration_ms: int,
) -> dict[str, bool]:
    if not benchmark_available:
        return {key: False for key in ACCEPTANCE_CHECK_KEYS}
    positive_classes = [
        metrics
        for metrics in (per_class or {}).values()
        if metrics.matchable_cases > 0
    ]
    return {
        "benchmarkAvailable": True,
        "precision": precision is not None and precision >= PRECISION_TARGET,
        "falsePositives": (
            false_positives is not None and false_positives <= FALSE_POSITIVE_LIMIT
        ),
        "matchRate": match_rate is not None and match_rate >= MATCH_RATE_TARGET,
        "endToEndAutonomy": (
            end_to_end_autonomy_rate is not None
            and end_to_end_autonomy_rate >= END_TO_END_AUTONOMY_TARGET
        ),
        "stageACorrectness": (
            stage_a is not None
            and stage_a.correctness_rate >= STAGE_CORRECTNESS_TARGET
        ),
        "stageBCorrectness": (
            stage_b is not None
            and stage_b.correctness_rate >= STAGE_CORRECTNESS_TARGET
        ),
        "positiveClassAccuracy": bool(positive_classes)
        and all(
            metrics.match_rate >= CLASS_ACCURACY_TARGET
            for metrics in positive_classes
        ),
        "exceptionRecall": exception_recall == EXCEPTION_RECALL_TARGET,
        "runtime": duration_ms <= RUNTIME_LIMIT_MS,
    }


def evaluate_predictions(
    truth: Iterable[Any] | Mapping[Any, Any],
    predictions: Iterable[Any] | Mapping[Any, Any],
    duration_ms: int,
    source_count: int | None = None,
    benchmark_available: bool = True,
    open_exception_count: int | None = None,
) -> EvaluationReport:
    """Evaluate persisted-style predictions without importing matcher modules."""
    truth_cases = _truth_cases(truth)
    prediction_values = _associate_predictions(truth_cases, _predictions(predictions))
    truth_by_id = {case.case_id: case for case in truth_cases}
    predictions_by_case: dict[str, list[Prediction]] = defaultdict(list)
    for prediction in prediction_values:
        if prediction.case_id is not None:
            predictions_by_case[prediction.case_id].append(prediction)

    autonomous_links = 0
    false_positive_total = 0
    open_exceptions = 0
    settlement_net = 0
    settlement_seen: set[tuple[str | None, int]] = set()
    reviewed_cases: dict[str, str] = {}

    per_class_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    correctly_resolved_cases: set[str] = set()
    autonomously_resolved_cases: set[str] = set()
    financially_resolved_cases: set[str] = set()
    recalled_exception_cases: set[str] = set()

    for prediction in prediction_values:
        case = truth_by_id.get(prediction.case_id or "")
        if prediction.autonomous:
            autonomous_links += len(prediction.selected_ids)
            false_positive_total += _autonomous_false_positive_count(case, prediction)
        if not prediction.autonomous and prediction.review_status not in {"approved", "rejected"}:
            open_exceptions += 1
        if prediction.review_status in {"approved", "rejected"} and prediction.case_id:
            reviewed_cases[prediction.case_id] = prediction.review_status
        if prediction.settlement_net is not None:
            key = (prediction.case_id, prediction.settlement_net)
            if key not in settlement_seen:
                settlement_seen.add(key)
                settlement_net += prediction.settlement_net

    for case in truth_cases:
        class_counts = per_class_counts[case.scenario_class]
        class_counts["cases"] += 1
        class_counts["matchable_cases"] += int(case.matchable)
        case_predictions = predictions_by_case.get(case.case_id, [])
        resolved = case.matchable and _case_is_correct(case, case_predictions)
        autonomously_resolved = _case_is_autonomously_resolved(case, case_predictions)
        financially_resolved = _case_is_financially_resolved(case, case_predictions)
        if _exception_is_recalled(case, case_predictions):
            recalled_exception_cases.add(case.case_id)
        if resolved:
            correctly_resolved_cases.add(case.case_id)
        if autonomously_resolved:
            autonomously_resolved_cases.add(case.case_id)
        if financially_resolved:
            financially_resolved_cases.add(case.case_id)
        if case.matchable and not financially_resolved:
            class_counts["financially_unresolved_cases"] += 1
        class_counts["open_exceptions"] += sum(
            not prediction.autonomous
            and prediction.review_status not in {"approved", "rejected"}
            for prediction in case_predictions
        )
        if resolved:
            class_counts["correctly_resolved"] += 1
        class_counts["autonomous_cases"] += int(autonomously_resolved)
        amount = case.amount
        if financially_resolved:
            class_counts["money_reconciled"] += amount
        else:
            class_counts["money_unresolved"] += amount

    if open_exception_count is not None:
        open_exceptions = open_exception_count

    matchable_cases_value = sum(case.matchable for case in truth_cases)
    correctly_resolved_value = sum(
        case.case_id in correctly_resolved_cases for case in truth_cases if case.matchable
    )
    money_reconciled_value = sum(
        case.amount for case in truth_cases if case.case_id in financially_resolved_cases
    )
    money_unresolved_value = sum(
        case.amount for case in truth_cases if case.case_id not in financially_resolved_cases
    )
    records_processed = source_count if source_count is not None else len(prediction_values)
    duration_ms = max(0, int(duration_ms))
    throughput = round(records_processed / (duration_ms / 1_000), 2) if duration_ms else 0.0
    precision_value = _percentage(
        max(0, autonomous_links - false_positive_total), autonomous_links
    )
    match_rate_value = _percentage(correctly_resolved_value, matchable_cases_value)
    end_to_end_autonomy_rate_value = _percentage(
        len(autonomously_resolved_cases), matchable_cases_value
    )
    exception_cases_value = sum(not case.matchable for case in truth_cases)
    exception_recall_value = _percentage(
        len(recalled_exception_cases), exception_cases_value
    )

    stage_metrics: dict[str, StageMetrics] | None = None
    if benchmark_available:
        stage_metrics = {}
        positive_cases = [case for case in truth_cases if case.matchable]
        for stage in _REQUIRED_STAGE_ORDER:
            stage_predictions = [
                prediction
                for prediction in prediction_values
                if prediction.stage == stage
            ]
            stage_case_predictions: dict[str, list[Prediction]] = defaultdict(list)
            for prediction in stage_predictions:
                if prediction.case_id in truth_by_id:
                    stage_case_predictions[prediction.case_id].append(prediction)
            stage_correctly_resolved = sum(
                _stage_case_is_correct(
                    case,
                    stage_case_predictions.get(case.case_id, []),
                    stage,
                )
                for case in positive_cases
            )
            stage_autonomous_cases = sum(
                _stage_case_is_autonomous(
                    case,
                    stage_case_predictions.get(case.case_id, []),
                    stage,
                )
                for case in positive_cases
            )
            stage_false_positives = sum(
                _autonomous_stage_false_positive_count(
                    truth_by_id.get(prediction.case_id or ""), prediction, stage
                )
                for prediction in stage_predictions
                if prediction.autonomous
            )
            stage_autonomous_links = sum(
                len(prediction.selected_ids)
                for prediction in stage_predictions
                if prediction.autonomous
            )
            stage_metrics[stage] = StageMetrics(
                eligible_cases=len(positive_cases),
                correctly_resolved=stage_correctly_resolved,
                correctness_rate=_percentage(
                    stage_correctly_resolved, len(positive_cases)
                ),
                autonomous_cases=stage_autonomous_cases,
                autonomy_rate=_percentage(stage_autonomous_cases, len(positive_cases)),
                autonomous_links=stage_autonomous_links,
                false_positives=stage_false_positives,
                precision=_percentage(
                    max(0, stage_autonomous_links - stage_false_positives),
                    stage_autonomous_links,
                ),
                unresolved_cases=len(positive_cases) - stage_correctly_resolved,
                open_exceptions=sum(
                    int(
                        not prediction.autonomous
                        and prediction.review_status not in {"approved", "rejected"}
                    )
                    for prediction in stage_predictions
                ),
                records_processed=len(stage_predictions),
            )

    per_class_value: dict[str, ClassMetrics] | None = None
    if benchmark_available:
        per_class_value = {}
        for scenario_class, counts in sorted(per_class_counts.items()):
            class_autonomous_links = sum(
                len(prediction.selected_ids)
                for prediction in prediction_values
                if prediction.autonomous
                and prediction.case_id in truth_by_id
                and truth_by_id[prediction.case_id].scenario_class == scenario_class
            )
            class_false_positives = sum(
                _autonomous_false_positive_count(
                    truth_by_id.get(prediction.case_id or ""), prediction
                )
                for prediction in prediction_values
                if prediction.autonomous
                and prediction.case_id in truth_by_id
                and truth_by_id[prediction.case_id].scenario_class == scenario_class
            )
            per_class_value[scenario_class] = ClassMetrics(
                scenario_class=scenario_class,
                cases=counts["cases"],
                matchable_cases=counts["matchable_cases"],
                correctly_resolved=counts["correctly_resolved"],
                match_rate=_percentage(
                    counts["correctly_resolved"], counts["matchable_cases"]
                ),
                autonomous_cases=counts["autonomous_cases"],
                false_positives=class_false_positives,
                precision=_percentage(
                    max(0, class_autonomous_links - class_false_positives),
                    class_autonomous_links,
                ),
                open_exceptions=counts["open_exceptions"],
                financially_unresolved_cases=counts["financially_unresolved_cases"],
                money_reconciled=counts["money_reconciled"],
                money_unresolved=counts["money_unresolved"],
            )

    approved_cases = sum(status == "approved" for status in reviewed_cases.values())
    rejected_cases = sum(status == "rejected" for status in reviewed_cases.values())
    approved_case_ids = {
        case_id for case_id, status in reviewed_cases.items() if status == "approved"
    }
    review_adjusted_resolved = len(financially_resolved_cases | approved_case_ids)
    review_adjusted_match_rate = (
        _percentage(
            sum(
                case.case_id in financially_resolved_cases
                or reviewed_cases.get(case.case_id) == "approved"
                for case in truth_cases
                if case.matchable
            ),
            matchable_cases_value,
        )
        if benchmark_available
        else None
    )
    review_adjusted = {
        "closedCases": review_adjusted_resolved
        + sum(
            status == "rejected"
            for case_id, status in reviewed_cases.items()
            if case_id not in financially_resolved_cases
        ),
        "reviewedCases": len(reviewed_cases),
        "approvedCases": approved_cases,
        "rejectedCases": rejected_cases,
        "resolvedCases": review_adjusted_resolved,
        "matchRate": review_adjusted_match_rate,
        "moneyReconciled": money_reconciled_value if benchmark_available else None,
    }
    false_positives_value = false_positive_total if benchmark_available else None
    precision = precision_value if benchmark_available else None
    match_rate = match_rate_value if benchmark_available else None
    end_to_end_autonomy_rate = (
        end_to_end_autonomy_rate_value if benchmark_available else None
    )
    exception_recall = exception_recall_value if benchmark_available else None
    stage_a = stage_metrics.get("ledger_to_razorpay") if stage_metrics else None
    stage_b = stage_metrics.get("razorpay_to_settlement") if stage_metrics else None
    acceptance_checks = _acceptance_checks(
        benchmark_available=benchmark_available,
        precision=precision,
        false_positives=false_positives_value,
        match_rate=match_rate,
        end_to_end_autonomy_rate=end_to_end_autonomy_rate,
        stage_a=stage_a,
        stage_b=stage_b,
        per_class=per_class_value,
        exception_recall=exception_recall,
        duration_ms=duration_ms,
    )
    return EvaluationReport(
        benchmark_available=benchmark_available,
        precision=precision,
        false_positives=false_positives_value,
        false_positive_rate=(
            _percentage(false_positive_total, autonomous_links)
            if benchmark_available
            else None
        ),
        match_rate=match_rate,
        end_to_end_autonomy_rate=end_to_end_autonomy_rate,
        exception_recall=exception_recall,
        correctly_resolved=(correctly_resolved_value if benchmark_available else None),
        matchable_cases=(matchable_cases_value if benchmark_available else None),
        autonomous_cases=(
            len(autonomously_resolved_cases) if benchmark_available else None
        ),
        open_exceptions=open_exceptions,
        financially_unresolved_cases=(
            sum(
                case.case_id not in financially_resolved_cases
                for case in truth_cases
                if case.matchable
            )
            if benchmark_available
            else None
        ),
        money_reconciled=(money_reconciled_value if benchmark_available else None),
        money_unresolved=(money_unresolved_value if benchmark_available else None),
        settlement_net=settlement_net,
        records_processed=records_processed,
        duration_ms=duration_ms,
        throughput=throughput,
        per_class=per_class_value,
        stage_metrics=stage_metrics,
        review_adjusted=review_adjusted,
        acceptance_checks=acceptance_checks,
        acceptance_passed=benchmark_available and all(acceptance_checks.values()),
    )


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """Convert the report to JSON-safe storage data without truth rows."""
    data = asdict(report)
    data["per_class"] = (
        {
            key: asdict(value) for key, value in report.per_class.items()
        }
        if report.per_class is not None
        else None
    )
    data["benchmarkAvailable"] = report.benchmark_available
    data["reportVersion"] = EVALUATION_REPORT_VERSION
    data["benchmarkUnavailable"] = report.benchmark_unavailable
    data["sourceThroughput"] = report.source_throughput
    data["acceptancePassed"] = report.acceptance_passed
    return data


def _source_id(value: Any) -> str:
    return str(value)


async def evaluate_run(
    session: AsyncSession,
    run_id: UUID,
) -> EvaluationReport:
    """Evaluate a completed run against hidden truth after result persistence."""
    run = await session.get(ReconciliationRun, run_id)
    if run is None:
        raise ValueError("Reconciliation run was not found")
    if _string(run.status) != RunStatus.completed.value:
        raise ValueError("Only completed reconciliation runs can be evaluated")

    batch = await session.get(Batch, run.batch_id)
    if batch is None:
        raise ValueError("Reconciliation batch was not found")

    result_rows = (
        await session.execute(
            select(ReconciliationResult)
            .where(ReconciliationResult.run_id == run.id)
            .order_by(ReconciliationResult.created_at, ReconciliationResult.id)
        )
    ).scalars().all()
    link_rows = (
        await session.execute(
            select(MatchLink).where(MatchLink.run_id == run.id).order_by(MatchLink.created_at)
        )
    ).scalars().all()
    exception_rows = (
        await session.execute(
            select(ReconciliationException).where(
                ReconciliationException.run_id == run.id
            )
        )
    ).scalars().all()
    settlement_rows = (
        await session.execute(
            select(Settlement).where(Settlement.batch_id == run.batch_id)
        )
    ).scalars().all()

    prediction_rows: list[Prediction] = []
    links_by_result: dict[UUID, list[MatchLink]] = defaultdict(list)
    for link in link_rows:
        links_by_result[link.result_id].append(link)

    if batch.ground_truth_available:
        case_rows = (
            await session.execute(
                select(EvaluationCase).where(EvaluationCase.batch_id == run.batch_id)
            )
        ).scalars().all()
        truth_link_rows = (
            await session.execute(
                select(GroundTruthLink).where(
                    GroundTruthLink.evaluation_case_id.in_(
                        [case.id for case in case_rows]
                    )
                )
            )
        ).scalars().all()
        truth_sources_by_case: dict[UUID, list[TruthSource]] = defaultdict(list)
        for truth_link in truth_link_rows:
            truth_sources_by_case[truth_link.evaluation_case_id].append(
                TruthSource(
                    source_type=truth_link.source_type,
                    source_id=_source_id(truth_link.source_id),
                )
            )
        truth = [
            TruthCase(
                case_id=str(case.id),
                scenario_class=case.scenario_class,
                amount=case.amount,
                matchable=case.matchable,
                expected_status=_string(case.expected_status),
                sources=tuple(truth_sources_by_case.get(case.id, [])),
            )
            for case in case_rows
        ]
    else:
        truth = []

    truth_id_by_source: dict[str, set[str]] = defaultdict(set)
    for case in truth:
        for source_id in case.source_ids:
            truth_id_by_source[source_id].add(case.case_id)
    settlement_amounts = {str(settlement.id): settlement.amount for settlement in settlement_rows}

    for result in result_rows:
        links = links_by_result.get(result.id, [])
        selected_ids = tuple(
            dict.fromkeys(
                (
                    *(str(link.source_id) for link in links),
                    *(str(item) for item in (result.selected_ids or [])),
                )
            )
        )
        if result.primary_source_id is not None:
            selected_ids = tuple(
                dict.fromkeys((str(result.primary_source_id), *selected_ids))
            )
        case_id = None
        primary_case_ids = (
            truth_id_by_source.get(str(result.primary_source_id), set())
            if result.primary_source_id is not None
            else set()
        )
        if len(primary_case_ids) == 1:
            case_id = next(iter(primary_case_ids))
        else:
            overlap_counts = sorted(
                (
                    sum(source_id in case.source_ids for source_id in selected_ids),
                    case.case_id,
                )
                for case in truth
            )
            overlap_counts = [item for item in overlap_counts if item[0] > 0]
            if overlap_counts:
                best_count, best_case_id = max(
                    overlap_counts, key=lambda item: (item[0], item[1])
                )
                tied = [item for item in overlap_counts if item[0] == best_count]
                if len(tied) == 1:
                    case_id = best_case_id
        settlement_net = sum(
            settlement_amounts.get(str(link.source_id), 0)
            for link in links
            if link.source_type == "settlement"
        )
        prediction_rows.append(
            Prediction(
                case_id=case_id,
                status=_string(result.status),
                selected_ids=selected_ids,
                autonomous=result.autonomous,
                amount=result.amount,
                settlement_net=settlement_net or None,
                stage=_string(result.stage),
                review_status=None,
            )
        )

    review_by_result = {
        exception.result_id: _string(exception.status)
        for exception in exception_rows
        if exception.result_id is not None
        and _string(exception.status)
        in {ExceptionStatus.approved.value, ExceptionStatus.rejected.value}
    }
    prediction_rows = [
        Prediction(
            case_id=prediction.case_id,
            status=prediction.status,
            selected_ids=prediction.selected_ids,
            autonomous=prediction.autonomous,
            amount=prediction.amount,
            settlement_net=prediction.settlement_net,
            stage=prediction.stage,
            review_status=review_by_result.get(result.id),
        )
        for result, prediction in zip(result_rows, prediction_rows)
    ]
    report = evaluate_predictions(
        truth,
        prediction_rows,
        duration_ms=run.duration_ms or 0,
        source_count=run.source_row_count,
        benchmark_available=batch.ground_truth_available,
        open_exception_count=sum(
            _string(exception.status) == ExceptionStatus.open.value
            for exception in exception_rows
        ),
    )
    report = replace(
        report,
        settlement_net=sum(settlement.amount for settlement in settlement_rows),
    )
    run.metrics = report_to_dict(report)
    await session.commit()
    return report
