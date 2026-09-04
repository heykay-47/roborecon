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
async def test_investigation_endpoint_persists_and_returns_advisory_result(client, monkeypatch):
    from app.ai.model import AIInvestigation, Citation, InvestigationMode
    from app.exception import router as exception_router

    exception_id = uuid4()
    citation_id = uuid4()
    investigation = AIInvestigation(
        investigation_id=uuid4(),
        exception_id=exception_id,
        run_id=uuid4(),
        batch_id=uuid4(),
        mode=InvestigationMode.deterministic_fallback,
        provider=None,
        model=None,
        recommendation="Review the persisted evidence.",
        confidence=0,
        citations=[Citation(source_type="ledger", source_id=citation_id)],
        tool_trace=[],
        error_code="provider_unavailable",
        error_message="No configured AI provider was available.",
    )
    investigate = AsyncMock(return_value=investigation)
    monkeypatch.setattr(exception_router, "investigate_exception", investigate, raising=False)

    response = await client.post(
        f"/exceptions/{exception_id}/investigate",
        json={"actor": " analyst-7 "},
    )

    assert response.status_code == 200
    assert response.json()["investigationId"] == str(investigation.investigation_id)
    assert response.json()["citations"] == [
        {"sourceType": "ledger", "sourceId": str(citation_id)}
    ]
    investigate.assert_awaited_once()
    assert investigate.await_args.args[1] == exception_id
    assert investigate.await_args.kwargs == {"actor": "analyst-7"}


def test_exception_response_exposes_created_at_and_ai_readiness():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.reconciliation.schema import ExceptionResponse

    response = ExceptionResponse.model_validate(
        SimpleNamespace(
            id=uuid4(),
            run_id=uuid4(),
            batch_id=uuid4(),
            result_id=None,
            status="open",
            exception_type="duplicate",
            source_type="ledger",
            source_id=uuid4(),
            amount=1_000,
            message="Duplicate source record",
            review_note=None,
            reviewed_by=None,
            reviewed_at=None,
            created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )
    )

    serialized = response.model_dump(mode="json", by_alias=True)

    assert serialized["createdAt"] == "2026-08-26T00:00:00Z"
    assert serialized["aiReady"] is True


def test_exception_priority_prefers_open_ready_high_value_and_older_cases():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.exception.router import _exception_sort_key

    older = SimpleNamespace(
        id=uuid4(),
        status="open",
        amount=10_000,
        exception_type="duplicate",
        created_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    higher_value = SimpleNamespace(
        id=uuid4(),
        status="open",
        amount=20_000,
        exception_type="amount_mismatch",
        created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    closed = SimpleNamespace(
        id=uuid4(),
        status="approved",
        amount=99_000,
        exception_type="duplicate",
        created_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )

    ordered = sorted(
        [closed, older, higher_value],
        key=lambda row: _exception_sort_key(row, ai_ready=row.status == "open"),
    )

    assert ordered == [higher_value, older, closed]


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
async def test_close_brief_returns_conflict_when_assessment_is_already_running(
    client, monkeypatch
):
    from app.reconciliation import router as reconciliation_router
    from app.reconciliation.close_brief import CloseBriefConflict

    assess = AsyncMock(side_effect=CloseBriefConflict("A close brief is already being generated"))
    monkeypatch.setattr(reconciliation_router, "assess_batch_close", assess)

    response = await client.post(
        f"/reconciliation-runs/{uuid4()}/close-brief",
        json={"actor": " analyst-7 "},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A close brief is already being generated"
    assess.assert_awaited_once()
    assert assess.await_args.kwargs["actor"] == "analyst-7"


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
