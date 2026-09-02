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
    ClassMetrics,
    EvaluationCase,
    EvaluationReport,
    GroundTruthLink,
    Prediction,
    TruthCase,
)
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import Settlement


MATCH_RATE_TARGET = 90.0
AUTONOMOUS_RATE_TARGET = 65.0
RUNTIME_LIMIT_MS = 5_000


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
        source_ids=_ids(value),
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


def _acceptance_checks(
    *,
    benchmark_available: bool,
    precision: float,
    false_positives: int,
    match_rate: float,
    autonomous_resolution_rate: float,
    duration_ms: int,
    per_class: dict[str, ClassMetrics],
) -> dict[str, bool]:
    checks = {
        "benchmarkAvailable": benchmark_available,
        "precision": precision >= 100.0,
        "falsePositives": false_positives == 0,
        "matchRate": match_rate >= MATCH_RATE_TARGET,
        "autonomousResolution": autonomous_resolution_rate >= AUTONOMOUS_RATE_TARGET,
        "runtime": duration_ms <= RUNTIME_LIMIT_MS,
        "scenarioClasses": bool(per_class),
    }
    if not benchmark_available:
        return {key: False for key in checks}
    return checks


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

    false_positives = 0
    autonomous_links = 0
    autonomous_cases: set[str] = set()
    open_exceptions = 0
    settlement_net = 0
    settlement_seen: set[tuple[str | None, int]] = set()
    reviewed_cases: dict[str, str] = {}

    per_class_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    correctly_resolved_cases: set[str] = set()
    financially_resolved_cases: set[str] = set()

    for prediction in prediction_values:
        case = truth_by_id.get(prediction.case_id or "")
        expected_ids = set(case.source_ids) if case is not None else set()
        if prediction.autonomous:
            selected_ids = set(prediction.selected_ids)
            autonomous_links += max(1, len(selected_ids))
            if prediction.case_id is not None:
                autonomous_cases.add(prediction.case_id)
            wrong_ids = selected_ids.difference(expected_ids)
            false_positives += len(wrong_ids) or (1 if not selected_ids else 0)
        if not prediction.autonomous and prediction.review_status not in {
            "approved",
            "rejected",
        }:
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
        statuses = {_string(prediction.status) for prediction in case_predictions}
        auto_predictions = [
            prediction for prediction in case_predictions if prediction.autonomous
        ]
        case_has_false_positive = any(
            set(prediction.selected_ids).difference(case.source_ids)
            or (prediction.autonomous and not prediction.selected_ids)
            for prediction in auto_predictions
        )
        status_correct = case.expected_status in statuses
        review_status = reviewed_cases.get(case.case_id)
        review_resolved = review_status == "approved"
        resolved = (status_correct and not case_has_false_positive) or review_resolved
        if resolved:
            correctly_resolved_cases.add(case.case_id)
        if (auto_predictions and not case_has_false_positive) or review_resolved:
            financially_resolved_cases.add(case.case_id)
        if case.matchable and not financially_resolved_cases.intersection({case.case_id}):
            class_counts["financially_unresolved_cases"] += 1
        class_counts["open_exceptions"] += sum(
            not prediction.autonomous
            and prediction.review_status not in {"approved", "rejected"}
            for prediction in case_predictions
        )
        if resolved:
            class_counts["correctly_resolved"] += 1
        class_counts["autonomous_cases"] += int(
            bool(auto_predictions and not case_has_false_positive)
        )
        amount = case.amount
        if financially_resolved_cases.intersection({case.case_id}):
            class_counts["money_reconciled"] += amount
        else:
            class_counts["money_unresolved"] += amount

    if open_exception_count is not None:
        open_exceptions = open_exception_count

    matchable_cases = sum(case.matchable for case in truth_cases)
    correctly_resolved = sum(
        case.case_id in correctly_resolved_cases for case in truth_cases if case.matchable
    )
    money_reconciled = sum(
        case.amount for case in truth_cases if case.case_id in financially_resolved_cases
    )
    money_unresolved = sum(
        case.amount for case in truth_cases if case.case_id not in financially_resolved_cases
    )
    records_processed = source_count if source_count is not None else len(prediction_values)
    duration_ms = max(0, int(duration_ms))
    throughput = round(records_processed / (duration_ms / 1_000), 2) if duration_ms else 0.0
    precision = _percentage(autonomous_links - false_positives, autonomous_links)
    match_rate = _percentage(correctly_resolved, matchable_cases)
    autonomous_resolution_rate = _percentage(len(autonomous_cases), len(truth_cases))

    stage_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for prediction in prediction_values:
        stage = prediction.stage or "unknown"
        stage_counts[stage]["records_processed"] += 1
        stage_counts[stage]["autonomous_cases"] += int(prediction.autonomous)
        if prediction.autonomous:
            case = truth_by_id.get(prediction.case_id or "")
            expected_ids = set(case.source_ids) if case is not None else set()
            stage_counts[stage]["false_positives"] += len(
                set(prediction.selected_ids).difference(expected_ids)
            ) or int(not prediction.selected_ids)
    stage_metrics = {
        stage: {
            **counts,
            "precision": _percentage(
                counts["autonomous_cases"] - counts["false_positives"],
                counts["autonomous_cases"],
            ),
        }
        for stage, counts in sorted(stage_counts.items())
    }

    per_class: dict[str, ClassMetrics] = {}
    for scenario_class, counts in sorted(per_class_counts.items()):
        class_autonomous_links = sum(
            1
            for prediction in prediction_values
            if prediction.case_id in truth_by_id
            and truth_by_id[prediction.case_id].scenario_class == scenario_class
            and prediction.autonomous
        )
        class_false_positives = sum(
            len(
                set(prediction.selected_ids).difference(
                    set(truth_by_id[prediction.case_id].source_ids)
                )
            )
            for prediction in prediction_values
            if prediction.autonomous
            and prediction.case_id in truth_by_id
            and truth_by_id[prediction.case_id].scenario_class == scenario_class
        )
        per_class[scenario_class] = ClassMetrics(
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
                class_autonomous_links - class_false_positives, class_autonomous_links
            ),
            open_exceptions=counts["open_exceptions"],
            financially_unresolved_cases=counts["financially_unresolved_cases"],
            money_reconciled=counts["money_reconciled"],
            money_unresolved=counts["money_unresolved"],
        )

    approved_cases = sum(status == "approved" for status in reviewed_cases.values())
    rejected_cases = sum(status == "rejected" for status in reviewed_cases.values())
    review_adjusted_resolved = len(
        financially_resolved_cases
        | {case_id for case_id, status in reviewed_cases.items() if status == "approved"}
    )
    review_adjusted_match_rate = _percentage(
        sum(
            case.case_id in financially_resolved_cases
            or reviewed_cases.get(case.case_id) == "approved"
            for case in truth_cases
            if case.matchable
        ),
        matchable_cases,
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
        "moneyReconciled": money_reconciled,
    }
    acceptance_checks = _acceptance_checks(
        benchmark_available=benchmark_available,
        precision=precision,
        false_positives=false_positives,
        match_rate=match_rate,
        autonomous_resolution_rate=autonomous_resolution_rate,
        duration_ms=duration_ms,
        per_class=per_class,
    )
    return EvaluationReport(
        benchmark_available=benchmark_available,
        precision=precision,
        false_positives=false_positives,
        false_positive_rate=_percentage(false_positives, autonomous_links),
        match_rate=match_rate,
        autonomous_resolution_rate=autonomous_resolution_rate,
        correctly_resolved=correctly_resolved,
        matchable_cases=matchable_cases,
        autonomous_cases=len(autonomous_cases),
        open_exceptions=open_exceptions,
        financially_unresolved_cases=sum(
            case.case_id not in financially_resolved_cases
            for case in truth_cases
            if case.matchable
        ),
        money_reconciled=money_reconciled,
        money_unresolved=money_unresolved,
        settlement_net=settlement_net,
        records_processed=records_processed,
        duration_ms=duration_ms,
        throughput=throughput,
        per_class=per_class,
        stage_metrics=stage_metrics,
        review_adjusted=review_adjusted,
        acceptance_checks=acceptance_checks,
        acceptance_passed=benchmark_available and all(acceptance_checks.values()),
    )


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """Convert the report to JSON-safe storage data without truth rows."""
    data = asdict(report)
    data["per_class"] = {
        key: asdict(value) for key, value in report.per_class.items()
    }
    data["benchmarkAvailable"] = report.benchmark_available
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
        truth_ids_by_case: dict[UUID, list[str]] = defaultdict(list)
        for truth_link in truth_link_rows:
            truth_ids_by_case[truth_link.evaluation_case_id].append(
                _source_id(truth_link.source_id)
            )
        truth = [
            TruthCase(
                case_id=str(case.id),
                scenario_class=case.scenario_class,
                amount=case.amount,
                matchable=case.matchable,
                expected_status=_string(case.expected_status),
                source_ids=tuple(truth_ids_by_case.get(case.id, [])),
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
        selected_ids = tuple(str(link.source_id) for link in links)
        if not selected_ids:
            selected_ids = tuple(str(item) for item in (result.selected_ids or []))
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
        exception.result_id: exception.status.value
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
