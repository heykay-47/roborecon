from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit_service
from app.audit.model import AuditEvent
from app.batch.model import Batch, IngestionRecord
from app.common.enums import AuditEventType, BatchKind, BatchStatus
from app.demo.dataset import DemoDataset, TruthCaseSeed, build_demo_dataset
from app.demo.source_service import persist_source_records
from app.demo.source_service import source_counts as _source_counts
from app.evaluation.model import EvaluationCase, GroundTruthLink
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.settlement.model import BankCredit, Settlement, SettlementLine

ROBORECON_TABLES = (
    GroundTruthLink,
    EvaluationCase,
    AuditEvent,
    BankCredit,
    SettlementLine,
    Settlement,
    RazorpayRefund,
    RazorpayPayment,
    RazorpayOrder,
    LedgerEntry,
    IngestionRecord,
    Batch,
)


def source_counts(dataset: DemoDataset) -> dict[str, int]:
    return _source_counts(dataset)


async def _clear_roborecon_tables(session: AsyncSession) -> None:
    for model in ROBORECON_TABLES:
        await session.execute(delete(model))


async def persist_demo_sources(
    session: AsyncSession, dataset: DemoDataset, batch: Batch
) -> None:
    """Persist canonical source records and quarantine rows, excluding truth."""
    await persist_source_records(session, dataset, batch)


def _truth_source_ids(case: TruthCaseSeed) -> Iterable[tuple[str, UUID]]:
    singular = (
        ("ledger", case.ledger_entry_id),
        ("razorpay_order", case.razorpay_order_id),
        ("razorpay_payment", case.razorpay_payment_id),
        ("razorpay_refund", case.razorpay_refund_id),
        ("settlement", case.settlement_id),
        ("bank_credit", case.bank_credit_id),
    )
    seen: set[tuple[str, UUID]] = set()
    for source_type, source_id in singular:
        if source_id is not None and (source_type, source_id) not in seen:
            seen.add((source_type, source_id))
            yield source_type, source_id
    for source_type, source_ids in (
        ("settlement", case.settlement_ids),
        ("bank_credit", case.bank_credit_ids),
    ):
        for source_id in source_ids:
            if (source_type, source_id) not in seen:
                seen.add((source_type, source_id))
                yield source_type, source_id


async def persist_demo_truth(
    session: AsyncSession, dataset: DemoDataset, batch: Batch
) -> None:
    """Persist evaluation cases and truth links separately from matcher inputs."""
    session.add_all(
        [
            EvaluationCase(
                id=case.case_id,
                batch_id=batch.id,
                case_key=str(case.case_id),
                scenario_class=case.scenario_class,
                amount=case.amount,
                matchable=case.matchable,
                expected_status=case.expected_status,
            )
            for case in dataset.truth_cases
        ]
    )
    session.add_all(
        [
            GroundTruthLink(
                evaluation_case_id=case.case_id,
                source_type=source_type,
                source_id=source_id,
            )
            for case in dataset.truth_cases
            for source_type, source_id in _truth_source_ids(case)
        ]
    )


async def reset_demo(session: AsyncSession) -> Batch:
    """Replace RoboRecon data with the fixed benchmark in one transaction."""
    dataset = build_demo_dataset()
    now = datetime.now(timezone.utc)
    batch = Batch(
        id=dataset.batch_id,
        kind=BatchKind.demo,
        status=BatchStatus.completed,
        seed=dataset.seed,
        ground_truth_available=True,
        source_row_count=dataset.source_row_count,
        started_at=now,
        completed_at=now,
    )

    async with session.begin():
        await _clear_roborecon_tables(session)
        session.expunge_all()
        session.add(batch)
        await session.flush()
        await persist_demo_sources(session, dataset, batch)
        await persist_demo_truth(session, dataset, batch)
        await audit_service.append_event(
            session,
            batch_id=batch.id,
            event_type=AuditEventType.demo_reset_completed,
            actor="demo",
            entity_type="batch",
            entity_id=batch.id,
            summary="Demo benchmark reset completed",
        )

    return batch
