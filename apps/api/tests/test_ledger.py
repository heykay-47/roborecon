from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.ledger import router as ledger_router


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
        "load_source_record_page",
        AsyncMock(return_value=([row], 1)),
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
        "load_source_record_page",
        AsyncMock(return_value=([row], 1)),
    )

    response = await client.get(
        f"/transactions?source_type=settlement_line&source_id={line_id}"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["sourceType"] == "settlement_line"
    assert response.json()["items"][0]["sourceId"] == str(line_id)


@pytest.mark.asyncio
async def test_transactions_pass_filters_and_pagination_to_database_page_loader(
    client, monkeypatch
):
    batch_id = uuid4()
    source_id = uuid4()
    row = record(batch_id, "ledger", source_id)
    load_page = AsyncMock(return_value=([row], 17))
    monkeypatch.setattr(ledger_router, "load_source_record_page", load_page)

    response = await client.get(
        "/transactions"
        f"?batch_id={batch_id}"
        "&source_type=ledger"
        f"&source_id={source_id}"
        "&status=payment"
        "&reconciliation_state=matched"
        "&page=3&page_size=1"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 17
    assert response.json()["page"] == 3
    assert response.json()["pageSize"] == 1
    assert load_page.await_count == 1
    call = load_page.await_args
    assert call.args[1:] == (batch_id, "ledger", source_id, "payment", "matched", 3, 1)
