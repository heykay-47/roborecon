from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.batch.model import Batch
from app.common.enums import BatchKind, BatchStatus, RunStatus
from app.reconciliation import service
from app.reconciliation.service import RunAlreadyRunning


class _ExecuteResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


def _empty_snapshot(batch):
    return (
        batch,
        {
            "ledger": [],
            "orders": [],
            "payments": [],
            "refunds": [],
            "settlements": [],
            "lines": [],
            "credits": [],
            "quarantine": [],
        },
        {
            "ledger": 0,
            "razorpayOrders": 0,
            "razorpayPayments": 0,
            "razorpayRefunds": 0,
            "settlements": 0,
            "bankCredits": 0,
            "quarantined": 0,
            "total": 0,
        },
    )


def _session(*, running=None):
    batch = Batch(
        id=uuid4(),
        kind=BatchKind.demo,
        status=BatchStatus.completed,
        ground_truth_available=True,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=batch)
    session.execute = AsyncMock(return_value=_ExecuteResult(running))
    session.connection = AsyncMock()
    session.begin = MagicMock(return_value=_Transaction())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    return session, batch


def _patch_empty_run(monkeypatch, batch):
    monkeypatch.setattr(
        service,
        "_load_snapshot",
        AsyncMock(return_value=_empty_snapshot(batch)),
    )
    monkeypatch.setattr(service, "_audit", AsyncMock())
    monkeypatch.setattr(service, "reconcile_stage_a", MagicMock(return_value=[]))
    monkeypatch.setattr(service, "reconcile_stage_b", MagicMock(return_value=[]))


@pytest.mark.asyncio
async def test_run_reconciliation_uses_repeatable_read_snapshot_transaction(monkeypatch):
    session, batch = _session()
    _patch_empty_run(monkeypatch, batch)

    run = await service.run_reconciliation(session, batch.id)

    assert run.status is RunStatus.completed
    session.connection.assert_awaited_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    assert session.begin.call_count == 1


@pytest.mark.asyncio
async def test_run_reconciliation_rejects_existing_running_run():
    session, batch = _session(running=object())

    with pytest.raises(RunAlreadyRunning):
        await service.run_reconciliation(session, batch.id)

    session.begin.assert_not_called()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_completed_runs_can_be_repeated_for_the_same_batch(monkeypatch):
    session, batch = _session()
    _patch_empty_run(monkeypatch, batch)

    first = await service.run_reconciliation(session, batch.id)
    second = await service.run_reconciliation(session, batch.id)

    assert first.status is RunStatus.completed
    assert second.status is RunStatus.completed
    assert session.begin.call_count == 2


@pytest.mark.asyncio
async def test_failed_execution_persists_sanitized_failed_run(monkeypatch):
    session, batch = _session()
    _patch_empty_run(monkeypatch, batch)
    monkeypatch.setattr(
        service,
        "reconcile_stage_a",
        MagicMock(side_effect=RuntimeError("database password leaked")),
    )

    with pytest.raises(RuntimeError, match="database password leaked"):
        await service.run_reconciliation(session, batch.id)

    failed_run = session.add.call_args_list[-1].args[0]
    assert failed_run.status is RunStatus.failed
    assert failed_run.error_message == "Reconciliation failed before completion."
    session.commit.assert_awaited_once()
