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
