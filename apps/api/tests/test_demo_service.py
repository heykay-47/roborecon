from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.batch.model import Batch
from app.common.enums import BatchKind, BatchStatus
from app.demo.dataset import build_demo_dataset
from app.demo.service import ROBORECON_TABLES, reset_demo
from app.demo.source_service import persist_source_records


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _AuditResult:
    def scalar_one_or_none(self):
        return SimpleNamespace()

    def scalar_one(self):
        return 0


class _Session:
    def __init__(self):
        self.deleted = []
        self.added = []

    def begin(self):
        return _Transaction()

    async def execute(self, statement):
        self.deleted.append(statement)
        return _AuditResult()

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    def expunge_all(self):
        return None

    async def flush(self):
        return None


class _SourceSession:
    def __init__(self):
        self.added = []
        self.flushes = []

    def add_all(self, values):
        self.added.extend(values)

    async def flush(self):
        self.flushes.append(tuple(type(value).__name__ for value in self.added))


@pytest.fixture
async def demo_client(client, monkeypatch):
    from app.config import settings
    from app.demo import router as demo_router

    monkeypatch.setattr(settings, "demo_mode", True)
    dataset = build_demo_dataset()

    async def fake_reset(session):
        now = datetime.now(timezone.utc)
        return Batch(
            id=dataset.batch_id,
            kind=BatchKind.demo,
            status=BatchStatus.completed,
            seed=dataset.seed,
            ground_truth_available=True,
            source_row_count=dataset.source_row_count,
            started_at=now,
            completed_at=now,
        )

    monkeypatch.setattr(demo_router, "reset_demo", fake_reset)
    return client


@pytest.mark.asyncio
async def test_reset_demo_persists_source_and_truth_in_one_transaction():
    session = _Session()

    first = await reset_demo(session)
    second = await reset_demo(session)

    assert first.id == second.id == build_demo_dataset().batch_id
    assert len(session.deleted) == 2 * (len(ROBORECON_TABLES) + 2)
    assert session.added[-1].event_type.value == "demo.reset.completed"


@pytest.mark.asyncio
async def test_reset_demo_deletes_reconciliation_children_before_batches():
    session = _Session()

    await reset_demo(session)

    deleted_tables = [
        statement.table.name
        for statement in session.deleted
        if hasattr(statement, "table")
    ]
    assert [
        table
        for table in (
            "ai_investigations",
            "match_links",
            "reconciliation_exceptions",
            "reconciliation_results",
            "reconciliation_runs",
            "batches",
        )
        if table in deleted_tables
    ] == [
        "ai_investigations",
        "match_links",
        "reconciliation_exceptions",
        "reconciliation_results",
        "reconciliation_runs",
        "batches",
    ]


@pytest.mark.asyncio
async def test_source_persistence_flushes_settlements_before_children():
    session = _SourceSession()

    await persist_source_records(
        session,
        build_demo_dataset(),
        SimpleNamespace(id=uuid4()),
    )

    assert len(session.flushes) == 1
    assert "Settlement" in session.flushes[0]
    assert "SettlementLine" not in session.flushes[0]
    assert "BankCredit" not in session.flushes[0]


@pytest.mark.asyncio
async def test_reset_demo_recreates_the_same_business_batch_id(demo_client):
    first = (await demo_client.post("/demo/reset")).json()
    second = (await demo_client.post("/demo/reset")).json()

    assert first["batchId"] == second["batchId"]
    assert first["sourceCounts"] == second["sourceCounts"]
