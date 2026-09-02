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
