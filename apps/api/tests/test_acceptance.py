from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.evaluation.model import ClassMetrics, StageMetrics
from app.evaluation.service import ACCEPTANCE_CHECK_KEYS, _acceptance_checks


def passing_acceptance_inputs():
    stage = StageMetrics(
        eligible_cases=20,
        correctly_resolved=20,
        correctness_rate=100,
        autonomous_cases=20,
        autonomy_rate=100,
        autonomous_links=60,
        false_positives=0,
        precision=100,
        unresolved_cases=0,
        open_exceptions=0,
        records_processed=20,
    )
    class_metrics = ClassMetrics(
        scenario_class="standard",
        cases=20,
        matchable_cases=20,
        correctly_resolved=20,
        match_rate=100,
        autonomous_cases=20,
        false_positives=0,
        precision=100,
        open_exceptions=0,
        financially_unresolved_cases=0,
        money_reconciled=200_000,
        money_unresolved=0,
    )
    return {
        "benchmark_available": True,
        "precision": 100.0,
        "false_positives": 0,
        "match_rate": 100.0,
        "end_to_end_autonomy_rate": 100.0,
        "stage_a": stage,
        "stage_b": stage,
        "per_class": {"standard": class_metrics},
        "exception_recall": 100.0,
        "duration_ms": 100,
    }


@pytest.mark.parametrize(
    ("failed_check", "mutate"),
    [
        ("precision", lambda values: values.update(precision=99.99)),
        ("falsePositives", lambda values: values.update(false_positives=1)),
        ("matchRate", lambda values: values.update(match_rate=94.99)),
        (
            "endToEndAutonomy",
            lambda values: values.update(end_to_end_autonomy_rate=89.99),
        ),
        (
            "stageACorrectness",
            lambda values: values.update(
                stage_a=replace(values["stage_a"], correctness_rate=89.99)
            ),
        ),
        (
            "stageBCorrectness",
            lambda values: values.update(
                stage_b=replace(values["stage_b"], correctness_rate=89.99)
            ),
        ),
        (
            "positiveClassAccuracy",
            lambda values: values.update(
                per_class={
                    "standard": replace(
                        values["per_class"]["standard"], match_rate=89.99
                    )
                }
            ),
        ),
        ("exceptionRecall", lambda values: values.update(exception_recall=99.99)),
        ("runtime", lambda values: values.update(duration_ms=5_001)),
    ],
)
def test_each_strict_acceptance_gate_fails_independently(failed_check, mutate):
    values = passing_acceptance_inputs()
    mutate(values)
    checks = _acceptance_checks(**values)

    assert checks[failed_check] is False
    assert set(checks) == set(ACCEPTANCE_CHECK_KEYS)


def test_acceptance_checks_have_exact_machine_contract():
    checks = _acceptance_checks(**passing_acceptance_inputs())

    assert tuple(checks) == ACCEPTANCE_CHECK_KEYS
    assert all(checks.values())


def _report(acceptance_passed: bool):
    stage = SimpleNamespace(autonomy_rate=100.0)
    class_metrics = SimpleNamespace(match_rate=100.0, precision=100.0)
    return SimpleNamespace(
        benchmark_available=True,
        precision=100.0,
        false_positives=0,
        match_rate=100.0,
        stage_metrics={
            "ledger_to_razorpay": stage,
            "razorpay_to_settlement": stage,
        },
        end_to_end_autonomy_rate=100.0,
        exception_recall=100.0,
        duration_ms=100,
        per_class={"standard": class_metrics},
        acceptance_checks={key: acceptance_passed for key in ACCEPTANCE_CHECK_KEYS},
        acceptance_passed=acceptance_passed,
    )


def test_acceptance_payload_and_exit_code():
    from app.demo.acceptance import acceptance_exit_code, acceptance_payload

    passing = _report(True)
    payload = acceptance_payload(passing)

    assert payload["stageAAutonomyRate"] == 100.0
    assert payload["stageBAutonomyRate"] == 100.0
    assert payload["endToEndAutonomyRate"] == 100.0
    assert payload["exceptionRecall"] == 100.0
    assert payload["acceptanceChecks"] == passing.acceptance_checks
    assert acceptance_exit_code(passing) == 0
    assert acceptance_exit_code(_report(False)) == 1
