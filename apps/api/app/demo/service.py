import json
from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.model import AuditEvent
from app.batch.model import Batch, IngestionRecord
from app.common.enums import AuditEventType, BatchKind, BatchStatus
from app.demo.dataset import DemoDataset, TruthCaseSeed, build_demo_dataset
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
    """Return deterministic counts for the top-level source rows in a demo batch."""
    counts = {
        "ledger": len(dataset.ledger_entries),
        "razorpayOrders": len(dataset.razorpay_orders),
        "razorpayPayments": len(dataset.razorpay_payments),
        "razorpayRefunds": len(dataset.razorpay_refunds),
        "settlements": len(dataset.settlements),
        "bankCredits": len(dataset.bank_credits),
        "quarantined": len(dataset.malformed_rows),
    }
    counts["total"] = sum(counts.values())
    return counts


async def _clear_roborecon_tables(session: AsyncSession) -> None:
    for model in ROBORECON_TABLES:
        await session.execute(delete(model))


async def persist_demo_sources(
    session: AsyncSession, dataset: DemoDataset, batch: Batch
) -> None:
    """Persist canonical source records and quarantine rows, excluding truth."""
    session.add_all(
        [
            LedgerEntry(
                id=entry.id,
                batch_id=batch.id,
                reference=entry.reference,
                entry_type=entry.entry_type,
                amount=entry.amount,
                currency=entry.currency,
                business_at=entry.business_at,
            )
            for entry in dataset.ledger_entries
        ]
    )
    session.add_all(
        [
            RazorpayOrder(
                id=order.id,
                batch_id=batch.id,
                provider_order_id=order.provider_order_id,
                receipt=order.receipt,
                amount=order.amount,
                currency=order.currency,
                status=order.status,
                business_at=order.business_at,
            )
            for order in dataset.razorpay_orders
        ]
    )
    session.add_all(
        [
            RazorpayPayment(
                id=payment.id,
                batch_id=batch.id,
                provider_payment_id=payment.provider_payment_id,
                provider_order_id=payment.provider_order_id,
                receipt=payment.receipt,
                amount=payment.amount,
                currency=payment.currency,
                status=payment.status,
                captured=payment.captured,
                business_at=payment.business_at,
            )
            for payment in dataset.razorpay_payments
        ]
    )
    session.add_all(
        [
            RazorpayRefund(
                id=refund.id,
                batch_id=batch.id,
                provider_refund_id=refund.provider_refund_id,
                provider_payment_id=refund.provider_payment_id,
                amount=refund.amount,
                currency=refund.currency,
                status=refund.status,
                business_at=refund.business_at,
            )
            for refund in dataset.razorpay_refunds
        ]
    )
    session.add_all(
        [
            Settlement(
                id=settlement.id,
                batch_id=batch.id,
                provider_settlement_id=settlement.provider_settlement_id,
                amount=settlement.amount,
                fee=settlement.fee,
                tax=settlement.tax,
                held_amount=settlement.held_amount,
                currency=settlement.currency,
                utr=settlement.utr,
                status=settlement.status,
                business_at=settlement.business_at,
            )
            for settlement in dataset.settlements
        ]
    )
    session.add_all(
        [
            SettlementLine(
                id=line.id,
                batch_id=batch.id,
                settlement_id=line.settlement_id,
                line_type=line.line_type,
                reference=line.reference,
                amount=line.amount,
                currency=line.currency,
                business_at=line.business_at,
            )
            for line in dataset.settlement_lines
        ]
    )
    session.add_all(
        [
            BankCredit(
                id=credit.id,
                batch_id=batch.id,
                settlement_id=credit.settlement_id,
                utr=credit.utr,
                amount=credit.amount,
                currency=credit.currency,
                business_at=credit.business_at,
            )
            for credit in dataset.bank_credits
        ]
    )
    session.add_all(
        [
            IngestionRecord(
                id=row.id,
                batch_id=batch.id,
                source_type=row.source_type,
                row_number=row.row_number,
                parse_status="quarantined",
                parse_error=row.parse_error,
                raw_payload=json.loads(row.raw_payload),
            )
            for row in dataset.malformed_rows
        ]
    )


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
        session.add(
            AuditEvent(
                batch_id=batch.id,
                event_type=AuditEventType.demo_reset_completed,
                sequence=1,
                actor="demo",
                entity_type="batch",
                entity_id=batch.id,
                occurred_at=now,
                summary="Demo benchmark reset completed",
            )
        )

    return batch
