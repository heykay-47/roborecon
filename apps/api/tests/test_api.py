from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_reset_requires_demo_mode(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)

    response = await client.post("/demo/reset")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_batches_and_transactions_use_paginated_items(client):
    batches = await client.get("/batches")
    transactions = await client.get("/transactions")

    assert batches.status_code == 200
    assert transactions.status_code == 200
    assert batches.json()["items"] == []
    assert transactions.json()["items"] == []


@pytest.mark.asyncio
async def test_exception_and_audit_collections_are_paginated(client):
    exceptions = await client.get("/exceptions?page=1&page_size=10")
    audit_events = await client.get("/audit-events?page=1&page_size=10")

    assert exceptions.status_code == 200
    assert exceptions.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 10,
    }
    assert audit_events.status_code == 200
    assert audit_events.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 10,
    }


@pytest.mark.asyncio
async def test_exception_endpoints_return_not_found_for_absent_ids(client):
    exception_id = uuid4()

    detail = await client.get(f"/exceptions/{exception_id}")
    review = await client.post(
        f"/exceptions/{exception_id}/review",
        json={"action": "reject", "actor": "analyst-7"},
    )

    assert detail.status_code == 404
    assert review.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_run_history_is_paginated(client):
    response = await client.get("/reconciliation-runs?page=1&page_size=10")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 10,
    }


@pytest.mark.asyncio
async def test_metrics_without_a_completed_run_returns_not_found(client):
    response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_for_a_run_without_metrics_returns_unavailable(client, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.common.enums import RunStatus
    from app.reconciliation import router as reconciliation_router

    run_id = uuid4()

    async def return_failed_run(session, requested_run_id):
        assert requested_run_id == run_id
        return SimpleNamespace(id=run_id, status=RunStatus.failed, metrics=None)

    monkeypatch.setattr(reconciliation_router, "_latest_run", return_failed_run)

    response = await client.get(f"/metrics?run_id={run_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Run metrics are not available"


def test_metrics_schema_serializes_strict_stage_and_end_to_end_fields():
    from app.reconciliation.schema import EvaluationReportSchema

    stage = {
        "eligible_cases": 1,
        "correctly_resolved": 1,
        "correctness_rate": 100.0,
        "autonomous_cases": 1,
        "autonomy_rate": 100.0,
        "autonomous_links": 3,
        "false_positives": 0,
        "precision": 100.0,
        "unresolved_cases": 0,
        "open_exceptions": 0,
        "records_processed": 1,
    }
    report = EvaluationReportSchema.model_validate(
        {
            "benchmark_available": True,
            "precision": 100.0,
            "false_positives": 0,
            "false_positive_rate": 0.0,
            "match_rate": 100.0,
            "end_to_end_autonomy_rate": 100.0,
            "exception_recall": 100.0,
            "correctly_resolved": 1,
            "matchable_cases": 1,
            "autonomous_cases": 1,
            "open_exceptions": 0,
            "financially_unresolved_cases": 0,
            "money_reconciled": 10_000,
            "money_unresolved": 0,
            "settlement_net": 9_764,
            "records_processed": 1,
            "duration_ms": 100,
            "throughput": 10.0,
            "per_class": None,
            "stage_metrics": {
                "ledger_to_razorpay": stage,
                "razorpay_to_settlement": stage,
            },
            "review_adjusted": {},
            "acceptance_checks": {},
            "acceptance_passed": True,
        }
    )

    serialized = report.model_dump(by_alias=True)

    assert serialized["endToEndAutonomyRate"] == 100.0
    assert serialized["exceptionRecall"] == 100.0
    assert serialized["stageMetrics"]["ledger_to_razorpay"]["autonomyRate"] == 100.0
    assert "autonomousResolutionRate" not in serialized


@pytest.mark.asyncio
async def test_completed_run_with_legacy_metrics_is_recomputed_before_schema_validation(
    monkeypatch,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.common.enums import RunStatus
    from app.reconciliation import router as reconciliation_router
    from app.reconciliation.schema import EvaluationReportSchema

    stage = {
        "eligible_cases": 1,
        "correctly_resolved": 1,
        "correctness_rate": 100.0,
        "autonomous_cases": 1,
        "autonomy_rate": 100.0,
        "autonomous_links": 3,
        "false_positives": 0,
        "precision": 100.0,
        "unresolved_cases": 0,
        "open_exceptions": 0,
        "records_processed": 1,
    }
    current_metrics = {
        "reportVersion": 1,
        "benchmark_available": True,
        "precision": 100.0,
        "false_positives": 0,
        "false_positive_rate": 0.0,
        "match_rate": 100.0,
        "end_to_end_autonomy_rate": 100.0,
        "exception_recall": 100.0,
        "correctly_resolved": 1,
        "matchable_cases": 1,
        "autonomous_cases": 1,
        "open_exceptions": 0,
        "financially_unresolved_cases": 0,
        "money_reconciled": 10_000,
        "money_unresolved": 0,
        "settlement_net": 9_764,
        "records_processed": 1,
        "duration_ms": 100,
        "throughput": 10.0,
        "per_class": None,
        "stage_metrics": {
            "ledger_to_razorpay": stage,
            "razorpay_to_settlement": stage,
        },
        "review_adjusted": {},
        "acceptance_checks": {},
        "acceptance_passed": True,
    }
    run = SimpleNamespace(
        id=uuid4(),
        status=RunStatus.completed,
        metrics={"precision": 100.0},
    )
    session = object()
    evaluate = AsyncMock(
        side_effect=lambda session, run_id: run.metrics.update(current_metrics)
    )
    monkeypatch.setattr(reconciliation_router, "evaluate_run", evaluate)

    await reconciliation_router._evaluate_if_needed(session, run)
    report = EvaluationReportSchema.model_validate(run.metrics)

    evaluate.assert_awaited_once_with(session, run.id)
    assert report.report_version == 1
    assert report.end_to_end_autonomy_rate == 100.0
