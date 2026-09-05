from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.batch.model import Batch
from app.common.enums import (
    BatchKind,
    BatchStatus,
    ReconciliationStage,
    ResultStatus,
    RunStatus,
)
from app.reconciliation import service
from app.reconciliation.model import EngineOutcome
from app.reconciliation.service import RunAlreadyRunning


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (ResultStatus.matched, "A possible match was found, but it needs review."),
        (ResultStatus.ambiguous, "More than one possible match was found. Review the evidence."),
        (ResultStatus.duplicate, "More than one source record matched. Review the evidence."),
        (ResultStatus.missing_razorpay, "No matching Razorpay record was found."),
        (ResultStatus.missing_ledger, "No matching ledger record was found."),
        (ResultStatus.missing_settlement, "No matching settlement was found."),
        (ResultStatus.missing_bank_credit, "No matching bank credit was found."),
        (ResultStatus.amount_mismatch, "The amounts do not match. Review the evidence."),
        (ResultStatus.malformed, "This source record could not be read. Review the source data."),
        (ResultStatus.confirmed_no_match, "No match was confirmed. Review the evidence."),
    ],
)
def test_exception_messages_are_plain_language(status, message):
    assert service._exception_message(status) == message


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
async def test_run_reconciliation_batches_result_persistence(monkeypatch):
    session, batch = _session()
    _patch_empty_run(monkeypatch, batch)
    outcome = EngineOutcome(
        status=ResultStatus.missing_razorpay,
        stage=ReconciliationStage.ledger_to_razorpay,
    )
    monkeypatch.setattr(service, "reconcile_stage_a", MagicMock(return_value=[outcome]))

    await service.run_reconciliation(session, batch.id, investigate=False)

    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_serverless_run_does_not_wait_for_advisory_investigation(monkeypatch):
    session, batch = _session()
    _patch_empty_run(monkeypatch, batch)
    investigate = AsyncMock()
    monkeypatch.setattr(service, "_investigate_after_commit", investigate)
    monkeypatch.setattr(service.settings, "serverless", True)

    await service.run_reconciliation(session, batch.id)

    investigate.assert_not_awaited()


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


def test_non_autonomous_stage_a_persists_source_links_and_exception(monkeypatch):
    class Captured:
        def __init__(self, **values):
            self.__dict__.update(values)

    monkeypatch.setattr(service, "MatchLink", Captured)
    monkeypatch.setattr(service, "ReconciliationException", Captured)

    run_id = uuid4()
    batch_id = uuid4()
    ledger_id = uuid4()
    payment_id = uuid4()
    order_id = uuid4()
    result = SimpleNamespace(
        id=uuid4(),
        primary_source_type="ledger",
        primary_source_id=ledger_id,
        stage=ReconciliationStage.ledger_to_razorpay,
        amount=10_000,
    )
    outcome = EngineOutcome(
        status=ResultStatus.ambiguous,
        selected_ids=[str(payment_id)],
        autonomous=False,
        stage=ReconciliationStage.ledger_to_razorpay,
    )
    source_index = {
        str(ledger_id): ("ledger", SimpleNamespace(id=ledger_id)),
        str(payment_id): (
            "razorpay_payment",
            SimpleNamespace(id=payment_id, provider_order_id="order-1"),
        ),
        str(order_id): (
            "razorpay_order",
            SimpleNamespace(id=order_id, provider_order_id="order-1"),
        ),
    }
    session = MagicMock()

    service._add_links_and_exception(
        session,
        run=SimpleNamespace(id=run_id),
        result=result,
        outcome=outcome,
        source_index=source_index,
        batch_id=batch_id,
    )

    added = [call.args[0] for call in session.add.call_args_list]
    links = [item for item in added if hasattr(item, "role")]
    exceptions = [item for item in added if hasattr(item, "exception_type")]
    assert {(link.source_type, link.source_id, link.role) for link in links} == {
        ("ledger", ledger_id, "primary"),
        ("razorpay_payment", payment_id, "selected"),
        ("razorpay_order", order_id, "related"),
    }
    assert all(link.autonomous is False for link in links)
    assert len(exceptions) == 1
    assert exceptions[0].message == "More than one possible match was found. Review the evidence."


@pytest.mark.asyncio
async def test_quarantined_rows_use_plain_language_exception_message(monkeypatch):
    session, batch = _session()
    _, source_rows, source_counts = _empty_snapshot(batch)
    source_rows["quarantine"] = [SimpleNamespace()]
    source_counts["quarantined"] = 1
    monkeypatch.setattr(
        service,
        "_load_snapshot",
        AsyncMock(return_value=(batch, source_rows, source_counts)),
    )
    monkeypatch.setattr(service, "_audit", AsyncMock())
    monkeypatch.setattr(service, "reconcile_stage_a", MagicMock(return_value=[]))
    monkeypatch.setattr(service, "reconcile_stage_b", MagicMock(return_value=[]))

    await service.run_reconciliation(session, batch.id)

    exceptions = [
        call.args[0]
        for call in session.add.call_args_list
        if getattr(call.args[0], "exception_type", None) == "malformed"
    ]
    assert len(exceptions) == 1
    assert exceptions[0].message == "This source record could not be read. Review the source data."
