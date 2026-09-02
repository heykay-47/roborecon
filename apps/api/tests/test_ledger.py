from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.common.enums import ExceptionStatus, ResultStatus
from app.ledger import router as ledger_router
from app.ledger.router import _attach_relationships


def record(batch_id, source_type, source_id):
    return {
        "source_type": source_type,
        "source_id": source_id,
        "reference": "REF-001",
        "amount": 10_000,
        "currency": "INR",
        "status": "paid",
        "business_at": datetime(2026, 8, 26, tzinfo=timezone.utc),
        "batch_id": batch_id,
        "reconciliation_state": "unreconciled",
        "parse_error": None,
        "run_id": None,
        "result_id": None,
        "exception_id": None,
    }


@pytest.mark.parametrize("parse_error", ["Missing receipt", None])
def test_quarantine_records_hide_parser_details(parse_error):
    row = ledger_router._record(
        source_type="quarantine",
        source_id=None,
        reference=None,
        amount=None,
        currency=None,
        status="quarantined",
        business_at=None,
        batch_id=uuid4(),
        parse_error=parse_error,
    )

    assert row["parse_error"] == "This source record could not be read. Review the source data."


def test_relationships_are_batch_scoped_and_exception_status_wins():
    batch_id = uuid4()
    other_batch_id = uuid4()
    source_id = uuid4()
    linked_source_id = uuid4()
    run_id = uuid4()
    result_id = uuid4()
    exception_id = uuid4()
    result = SimpleNamespace(
        id=result_id,
        batch_id=batch_id,
        run_id=run_id,
        stage="ledger_to_razorpay",
        status=ResultStatus.matched,
        primary_source_type="ledger",
        primary_source_id=source_id,
        autonomous=True,
        created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
    )
    link = SimpleNamespace(
        id=uuid4(),
        run_id=run_id,
        result_id=result_id,
        source_type="razorpay_payment",
        source_id=linked_source_id,
        autonomous=True,
        created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
    )
    exception = SimpleNamespace(
        id=exception_id,
        run_id=run_id,
        result_id=result_id,
        batch_id=batch_id,
        status=ExceptionStatus.open,
        source_type="ledger",
        source_id=source_id,
        created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
    )
    run = SimpleNamespace(
        id=run_id,
        batch_id=batch_id,
        started_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
    )
    rows = [
        record(batch_id, "ledger", source_id),
        record(batch_id, "razorpay_payment", linked_source_id),
        record(other_batch_id, "ledger", source_id),
    ]

    _attach_relationships(rows, [result], [link], [exception], [run])

    assert rows[0]["run_id"] == run_id
    assert rows[0]["result_id"] == result_id
    assert rows[0]["exception_id"] == exception_id
    assert rows[0]["reconciliation_state"] == "open"
    assert rows[1]["run_id"] == run_id
    assert rows[1]["result_id"] == result_id
    assert rows[1]["reconciliation_state"] == "autonomous"
    assert rows[2]["reconciliation_state"] == "unreconciled"
    assert rows[2]["run_id"] is None


def test_relationship_state_uses_autonomous_then_matched_then_unreconciled():
    batch_id = uuid4()
    autonomous_source_id = uuid4()
    matched_source_id = uuid4()
    unresolved_source_id = uuid4()
    autonomous_result_id = uuid4()
    matched_result_id = uuid4()

    def make_result(result_id, source_id, autonomous, status):
        return SimpleNamespace(
            id=result_id,
            batch_id=batch_id,
            run_id=uuid4(),
            stage="ledger_to_razorpay",
            status=status,
            primary_source_type="ledger",
            primary_source_id=source_id,
            autonomous=autonomous,
            created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        )

    rows = [
        record(batch_id, "ledger", autonomous_source_id),
        record(batch_id, "ledger", matched_source_id),
        record(batch_id, "ledger", unresolved_source_id),
    ]
    autonomous_result = make_result(
        autonomous_result_id, autonomous_source_id, True, ResultStatus.matched
    )
    matched_result = make_result(
        matched_result_id, matched_source_id, False, ResultStatus.matched
    )
    unresolved_result = make_result(
        uuid4(), unresolved_source_id, False, ResultStatus.ambiguous
    )
    runs = [
        SimpleNamespace(
            id=result.run_id,
            batch_id=batch_id,
            started_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
            created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        )
        for result in [autonomous_result, matched_result, unresolved_result]
    ]

    _attach_relationships(
        rows,
        [autonomous_result, matched_result, unresolved_result],
        [],
        [],
        runs,
    )

    assert rows[0]["reconciliation_state"] == "autonomous"
    assert rows[1]["reconciliation_state"] == "matched"
    assert rows[2]["reconciliation_state"] == "unreconciled"


def test_newer_run_wins_before_within_run_exception_precedence():
    batch_id = uuid4()
    source_id = uuid4()
    old_run_id = uuid4()
    new_run_id = uuid4()
    old_result_id = uuid4()
    new_result_id = uuid4()
    old_exception_id = uuid4()
    old_run = SimpleNamespace(
        id=old_run_id,
        batch_id=batch_id,
        started_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
    )
    new_run = SimpleNamespace(
        id=new_run_id,
        batch_id=batch_id,
        started_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
    )
    old_result = SimpleNamespace(
        id=old_result_id,
        batch_id=batch_id,
        run_id=old_run_id,
        status=ResultStatus.matched,
        primary_source_type="ledger",
        primary_source_id=source_id,
        autonomous=True,
        created_at=datetime(2026, 8, 26, 9, 1, tzinfo=timezone.utc),
    )
    new_result = SimpleNamespace(
        id=new_result_id,
        batch_id=batch_id,
        run_id=new_run_id,
        status=ResultStatus.matched,
        primary_source_type="ledger",
        primary_source_id=source_id,
        autonomous=False,
        created_at=datetime(2026, 8, 26, 10, 1, tzinfo=timezone.utc),
    )
    old_exception = SimpleNamespace(
        id=old_exception_id,
        batch_id=batch_id,
        run_id=old_run_id,
        result_id=old_result_id,
        status=ExceptionStatus.open,
        source_type="ledger",
        source_id=source_id,
        created_at=datetime(2026, 8, 26, 9, 2, tzinfo=timezone.utc),
    )
    rows = [record(batch_id, "ledger", source_id)]

    _attach_relationships(
        rows,
        [old_result, new_result],
        [],
        [old_exception],
        [old_run, new_run],
    )

    assert rows[0]["run_id"] == new_run_id
    assert rows[0]["result_id"] == new_result_id
    assert rows[0]["exception_id"] is None
    assert rows[0]["reconciliation_state"] == "matched"


def test_non_autonomous_link_inherits_unresolved_parent_result_state():
    batch_id = uuid4()
    primary_source_id = uuid4()
    linked_source_id = uuid4()
    run_id = uuid4()
    result_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        batch_id=batch_id,
        started_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
    )
    result = SimpleNamespace(
        id=result_id,
        batch_id=batch_id,
        run_id=run_id,
        status=ResultStatus.amount_mismatch,
        primary_source_type="ledger",
        primary_source_id=primary_source_id,
        autonomous=False,
        created_at=datetime(2026, 8, 26, 9, 1, tzinfo=timezone.utc),
    )
    link = SimpleNamespace(
        id=uuid4(),
        run_id=run_id,
        result_id=result_id,
        source_type="razorpay_payment",
        source_id=linked_source_id,
        autonomous=False,
        created_at=datetime(2026, 8, 26, 9, 2, tzinfo=timezone.utc),
    )
    rows = [
        record(batch_id, "ledger", primary_source_id),
        record(batch_id, "razorpay_payment", linked_source_id),
    ]

    _attach_relationships(rows, [result], [link], [], [run])

    assert rows[0]["reconciliation_state"] == "unreconciled"
    assert rows[1]["reconciliation_state"] == "unreconciled"
    assert rows[1]["run_id"] == run_id
    assert rows[1]["result_id"] == result_id


@pytest.mark.asyncio
async def test_transactions_api_serializes_relationship_fields(client, monkeypatch):
    batch_id = uuid4()
    run_id = uuid4()
    result_id = uuid4()
    exception_id = uuid4()
    row = record(batch_id, "ledger", uuid4())
    row.update(
        run_id=run_id,
        result_id=result_id,
        exception_id=exception_id,
        reconciliation_state="open",
    )
    monkeypatch.setattr(
        ledger_router,
        "_load_source_records",
        AsyncMock(return_value=[row]),
    )

    response = await client.get("/transactions")

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "sourceType": "ledger",
        "sourceId": str(row["source_id"]),
        "reference": "REF-001",
        "amount": 10_000,
        "currency": "INR",
        "status": "paid",
        "businessAt": "2026-08-26T00:00:00Z",
        "batchId": str(batch_id),
        "reconciliationState": "open",
        "parseError": None,
        "runId": str(run_id),
        "resultId": str(result_id),
        "exceptionId": str(exception_id),
    }


@pytest.mark.asyncio
async def test_transactions_support_settlement_line_source_and_id_filters(client, monkeypatch):
    line_id = uuid4()
    row = record(uuid4(), "settlement_line", line_id)
    monkeypatch.setattr(
        ledger_router,
        "_load_source_records",
        AsyncMock(return_value=[row]),
    )

    response = await client.get(
        f"/transactions?source_type=settlement_line&source_id={line_id}"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["sourceType"] == "settlement_line"
    assert response.json()["items"][0]["sourceId"] == str(line_id)
