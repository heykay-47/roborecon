from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError


@pytest.fixture
async def postgres_source_records():
    from app.database import async_session, engine
    from app.database_init import initialize_database

    try:
        await initialize_database()
        await initialize_database()
    except (DBAPIError, OSError) as error:
        pytest.skip(f"PostgreSQL integration container is unavailable: {error}")

    from app.batch.model import Batch, IngestionRecord
    from app.common.enums import (
        BatchKind,
        BatchStatus,
        ExceptionStatus,
        LedgerEntryType,
        RazorpayPaymentStatus,
        ReconciliationStage,
        ResultStatus,
        RunStatus,
        SettlementLineType,
    )
    from app.ledger.model import LedgerEntry
    from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
    from app.reconciliation.model import (
        MatchLink,
        ReconciliationException,
        ReconciliationResult,
        ReconciliationRun,
    )
    from app.settlement.model import BankCredit, Settlement, SettlementLine

    batch_id = uuid4()
    other_batch_id = uuid4()
    ledger_id = uuid4()
    order_id = uuid4()
    payment_id = uuid4()
    refund_id = uuid4()
    settlement_id = uuid4()
    line_id = uuid4()
    bank_credit_id = uuid4()
    ingestion_id = uuid4()
    other_ledger_id = uuid4()
    old_run_id = uuid4()
    new_run_id = uuid4()
    cross_batch_run_id = uuid4()
    old_result_id = uuid4()
    new_result_id = uuid4()
    matched_result_id = uuid4()
    unmatched_result_id = uuid4()
    cross_batch_result_id = uuid4()
    exception_id = uuid4()
    partial_exception_id = uuid4()
    link_id = uuid4()
    ledger_link_id = uuid4()
    unmatched_link_id = uuid4()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async with async_session() as session:
        async with session.begin():
            session.add_all(
                [
                    Batch(
                        id=batch_id,
                        kind=BatchKind.demo,
                        status=BatchStatus.completed,
                        seed="source-read-model",
                        ground_truth_available=False,
                        source_row_count=8,
                        started_at=now,
                        completed_at=now,
                    ),
                    Batch(
                        id=other_batch_id,
                        kind=BatchKind.test_mode_sync,
                        status=BatchStatus.completed,
                        seed="source-read-model-other",
                        ground_truth_available=False,
                        source_row_count=1,
                        started_at=now,
                        completed_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    LedgerEntry(
                        id=ledger_id,
                        batch_id=batch_id,
                        reference="LEDGER-1",
                        entry_type=LedgerEntryType.payment,
                        amount=10_000,
                        currency="INR",
                        business_at=now + timedelta(days=1),
                    ),
                    RazorpayOrder(
                        id=order_id,
                        batch_id=batch_id,
                        provider_order_id="order_1",
                        receipt="ORDER-1",
                        amount=10_000,
                        currency="INR",
                        status="created",
                        business_at=now + timedelta(days=2),
                    ),
                    RazorpayPayment(
                        id=payment_id,
                        batch_id=batch_id,
                        provider_payment_id="pay_1",
                        provider_order_id="order_1",
                        receipt="ORDER-1",
                        amount=10_000,
                        currency="INR",
                        status=RazorpayPaymentStatus.captured,
                        captured=True,
                        business_at=now + timedelta(days=3),
                    ),
                    RazorpayRefund(
                        id=refund_id,
                        batch_id=batch_id,
                        provider_refund_id="rfnd_1",
                        provider_payment_id="pay_1",
                        amount=1_000,
                        currency="INR",
                        status="processed",
                        business_at=now + timedelta(days=4),
                    ),
                    Settlement(
                        id=settlement_id,
                        batch_id=batch_id,
                        provider_settlement_id="setl_1",
                        amount=9_000,
                        fee=500,
                        tax=500,
                        held_amount=0,
                        currency="INR",
                        utr="utr_1",
                        status="processed",
                        business_at=now + timedelta(days=5),
                    ),
                    IngestionRecord(
                        id=ingestion_id,
                        batch_id=batch_id,
                        source_type="ledger",
                        row_number=99,
                        parse_status="quarantined",
                        parse_error="private parser detail",
                        raw_payload={"reference": "bad"},
                    ),
                    LedgerEntry(
                        id=other_ledger_id,
                        batch_id=other_batch_id,
                        reference="OTHER-1",
                        entry_type=LedgerEntryType.payment,
                        amount=1_000,
                        currency="INR",
                        business_at=now + timedelta(days=1),
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    SettlementLine(
                        id=line_id,
                        batch_id=batch_id,
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.payment,
                        reference="LINE-1",
                        amount=10_000,
                        currency="INR",
                        business_at=now + timedelta(days=6),
                    ),
                    BankCredit(
                        id=bank_credit_id,
                        batch_id=batch_id,
                        settlement_id=settlement_id,
                        utr="utr_1",
                        amount=9_000,
                        currency="INR",
                        business_at=now + timedelta(days=7),
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ReconciliationRun(
                        id=old_run_id,
                        batch_id=batch_id,
                        status=RunStatus.completed,
                        started_at=now - timedelta(days=2),
                        completed_at=now - timedelta(days=2),
                        source_row_count=1,
                        source_counts={},
                        metrics=None,
                    ),
                    ReconciliationRun(
                        id=new_run_id,
                        batch_id=batch_id,
                        status=RunStatus.completed,
                        started_at=now + timedelta(days=10),
                        completed_at=now + timedelta(days=10),
                        source_row_count=1,
                        source_counts={},
                        metrics=None,
                    ),
                    ReconciliationRun(
                        id=cross_batch_run_id,
                        batch_id=other_batch_id,
                        status=RunStatus.completed,
                        started_at=now + timedelta(days=20),
                        completed_at=now + timedelta(days=20),
                        source_row_count=1,
                        source_counts={},
                        metrics=None,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ReconciliationResult(
                        id=old_result_id,
                        run_id=old_run_id,
                        batch_id=batch_id,
                        stage=ReconciliationStage.ledger_to_razorpay,
                        status=ResultStatus.matched,
                        primary_source_type="ledger",
                        primary_source_id=ledger_id,
                        amount=10_000,
                        currency="INR",
                        score=100,
                        runner_up_score=0,
                        margin=100,
                        autonomous=True,
                        selected_ids=[],
                        evidence=[],
                        candidates=[],
                    ),
                    ReconciliationResult(
                        id=new_result_id,
                        run_id=new_run_id,
                        batch_id=batch_id,
                        stage=ReconciliationStage.ledger_to_razorpay,
                        status=ResultStatus.matched,
                        primary_source_type="ledger",
                        primary_source_id=ledger_id,
                        amount=10_000,
                        currency="INR",
                        score=90,
                        runner_up_score=0,
                        margin=90,
                        autonomous=False,
                        selected_ids=[],
                        evidence=[],
                        candidates=[],
                    ),
                    ReconciliationResult(
                        id=matched_result_id,
                        run_id=new_run_id,
                        batch_id=batch_id,
                        stage=ReconciliationStage.ledger_to_razorpay,
                        status=ResultStatus.matched,
                        primary_source_type="settlement",
                        primary_source_id=settlement_id,
                        amount=9_000,
                        currency="INR",
                        score=91,
                        runner_up_score=0,
                        margin=91,
                        autonomous=False,
                        selected_ids=[],
                        evidence=[],
                        candidates=[],
                    ),
                    ReconciliationResult(
                        id=unmatched_result_id,
                        run_id=new_run_id,
                        batch_id=batch_id,
                        stage=ReconciliationStage.ledger_to_razorpay,
                        status=ResultStatus.ambiguous,
                        primary_source_type="razorpay_order",
                        primary_source_id=order_id,
                        amount=10_000,
                        currency="INR",
                        score=70,
                        runner_up_score=60,
                        margin=10,
                        autonomous=False,
                        selected_ids=[],
                        evidence=[],
                        candidates=[],
                    ),
                    ReconciliationResult(
                        id=cross_batch_result_id,
                        run_id=cross_batch_run_id,
                        batch_id=batch_id,
                        stage=ReconciliationStage.ledger_to_razorpay,
                        status=ResultStatus.matched,
                        primary_source_type="ledger",
                        primary_source_id=ledger_id,
                        amount=10_000,
                        currency="INR",
                        score=100,
                        runner_up_score=0,
                        margin=100,
                        autonomous=True,
                        selected_ids=[],
                        evidence=[],
                        candidates=[],
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    MatchLink(
                        id=link_id,
                        run_id=new_run_id,
                        result_id=new_result_id,
                        source_type="razorpay_payment",
                        source_id=payment_id,
                        role="selected",
                        autonomous=True,
                        actor="system",
                    ),
                    MatchLink(
                        id=ledger_link_id,
                        run_id=new_run_id,
                        result_id=new_result_id,
                        source_type="ledger",
                        source_id=ledger_id,
                        role="selected",
                        autonomous=True,
                        actor="system",
                    ),
                    MatchLink(
                        id=unmatched_link_id,
                        run_id=new_run_id,
                        result_id=unmatched_result_id,
                        source_type="razorpay_refund",
                        source_id=refund_id,
                        role="selected",
                        autonomous=True,
                        actor="system",
                    ),
                    ReconciliationException(
                        id=exception_id,
                        run_id=new_run_id,
                        result_id=new_result_id,
                        batch_id=batch_id,
                        status=ExceptionStatus.open,
                        exception_type="review_required",
                        source_type="ledger",
                        source_id=ledger_id,
                        amount=10_000,
                        message="Review required",
                    ),
                    ReconciliationException(
                        id=partial_exception_id,
                        run_id=new_run_id,
                        result_id=new_result_id,
                        batch_id=batch_id,
                        status=ExceptionStatus.open,
                        exception_type="malformed_relationship",
                        source_type=None,
                        source_id=payment_id,
                        amount=10_000,
                        message="Malformed relationship",
                    ),
                ]
            )

    try:
        from app.database import get_session
        from app.main import app

        async def real_session():
            async with async_session() as session:
                yield session

        app.dependency_overrides[get_session] = real_session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield (
                client,
                batch_id,
                other_batch_id,
                new_run_id,
                new_result_id,
                exception_id,
            )
    finally:
        app.dependency_overrides.pop(get_session, None)
        async with async_session() as session:
            async with session.begin():
                for model, ids in (
                    (
                        ReconciliationException,
                        [exception_id, partial_exception_id],
                    ),
                    (MatchLink, [link_id, ledger_link_id, unmatched_link_id]),
                    (
                        ReconciliationResult,
                        [
                            old_result_id,
                            new_result_id,
                            matched_result_id,
                            unmatched_result_id,
                            cross_batch_result_id,
                        ],
                    ),
                    (
                        ReconciliationRun,
                        [old_run_id, new_run_id, cross_batch_run_id],
                    ),
                    (IngestionRecord, [ingestion_id]),
                    (BankCredit, [bank_credit_id]),
                    (SettlementLine, [line_id]),
                    (Settlement, [settlement_id]),
                    (RazorpayRefund, [refund_id]),
                    (RazorpayPayment, [payment_id]),
                    (RazorpayOrder, [order_id]),
                    (LedgerEntry, [ledger_id, other_ledger_id]),
                    (Batch, [batch_id, other_batch_id]),
                ):
                    await session.execute(delete(model).where(model.id.in_(ids)))
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_records_page_in_database_preserves_filters_and_relationship_state(
    postgres_source_records,
):
    (
        client,
        batch_id,
        other_batch_id,
        new_run_id,
        new_result_id,
        exception_id,
    ) = postgres_source_records

    response = await client.get(
        f"/transactions?batch_id={batch_id}&page=1&page_size=3"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert [item["sourceType"] for item in payload["items"]] == [
        "ledger",
        "razorpay_order",
        "razorpay_payment",
    ]
    assert payload["items"][0]["reconciliationState"] == "open"
    assert payload["items"][0]["exceptionId"] is not None
    assert payload["items"][0]["runId"] == str(new_run_id)
    assert payload["items"][0]["resultId"] == str(new_result_id)
    assert payload["items"][0]["exceptionId"] == str(exception_id)
    assert payload["items"][1]["reconciliationState"] == "unreconciled"
    assert payload["items"][1]["resultId"] is not None
    assert payload["items"][2]["reconciliationState"] == "autonomous"
    assert payload["items"][2]["resultId"] is not None
    assert payload["items"][2]["exceptionId"] is None

    second_page = await client.get(
        f"/transactions?batch_id={batch_id}&page=2&page_size=3"
    )
    assert [item["sourceType"] for item in second_page.json()["items"]] == [
        "razorpay_refund",
        "settlement",
        "settlement_line",
    ]
    assert second_page.json()["total"] == 8
    assert second_page.json()["items"][0]["reconciliationState"] == "unreconciled"
    assert second_page.json()["items"][1]["reconciliationState"] == "matched"

    payment_status = await client.get(
        f"/transactions?batch_id={batch_id}&status=payment"
    )
    assert payment_status.json()["total"] == 2
    assert {item["sourceType"] for item in payment_status.json()["items"]} == {
        "ledger",
        "settlement_line",
    }

    unreconciled = await client.get(
        f"/transactions?batch_id={batch_id}&reconciliation_state=unreconciled"
    )
    assert unreconciled.json()["total"] == 5

    no_quarantine_source_id = await client.get(
        f"/transactions?batch_id={batch_id}&source_type=quarantine&source_id={uuid4()}"
    )
    assert no_quarantine_source_id.json()["total"] == 0

    quarantine = await client.get(
        f"/transactions?batch_id={batch_id}&source_type=quarantine"
    )
    assert quarantine.json()["total"] == 1
    assert quarantine.json()["items"][0]["parseError"] == (
        "This source record could not be read. Review the source data."
    )

    other_batch = await client.get(f"/transactions?batch_id={other_batch_id}")
    assert other_batch.json()["total"] == 1
    assert other_batch.json()["items"][0]["reference"] == "OTHER-1"

    batches = await client.get("/batches?page=1&page_size=1")
    assert batches.json()["total"] >= 2
    assert len(batches.json()["items"]) == 1

    runs = await client.get(
        f"/reconciliation-runs?batch_id={batch_id}&page_size=1"
    )
    assert runs.json()["total"] == 2
    assert len(runs.json()["items"]) == 1
    assert runs.json()["items"][0]["batchId"] == str(batch_id)

    exceptions = await client.get(f"/exceptions?batch_id={batch_id}")
    assert exceptions.json()["total"] == 2
    assert exceptions.json()["items"][0]["aiReady"] is True


@pytest.mark.asyncio
async def test_source_record_reads_do_not_invoke_evaluation_or_advisory_ai(
    postgres_source_records,
    monkeypatch,
):
    from app.ai import investigator
    from app.evaluation import service as evaluation_service

    client, batch_id, *_ = postgres_source_records
    evaluate = AsyncMock()
    investigate = AsyncMock()
    monkeypatch.setattr(evaluation_service, "evaluate_run", evaluate)
    monkeypatch.setattr(investigator, "investigate_exception", investigate)

    response = await client.get(
        f"/transactions?batch_id={batch_id}&page=1&page_size=5"
    )

    assert response.status_code == 200
    evaluate.assert_not_awaited()
    investigate.assert_not_awaited()
