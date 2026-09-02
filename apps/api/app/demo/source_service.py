import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import Batch, IngestionRecord
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.settlement.model import BankCredit, Settlement, SettlementLine


def source_counts(snapshot: Any) -> dict[str, int]:
    """Return counts for persisted source rows, excluding settlement detail lines."""
    counts = {
        "ledger": len(snapshot.ledger_entries),
        "razorpayOrders": len(snapshot.razorpay_orders),
        "razorpayPayments": len(snapshot.razorpay_payments),
        "razorpayRefunds": len(snapshot.razorpay_refunds),
        "settlements": len(snapshot.settlements),
        "bankCredits": len(snapshot.bank_credits),
        "quarantined": len(snapshot.malformed_rows),
    }
    counts["total"] = sum(counts.values())
    return counts


async def persist_source_records(
    session: AsyncSession, snapshot: Any, batch: Batch
) -> None:
    """Persist canonical source rows without importing evaluation/truth models."""
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
            for entry in snapshot.ledger_entries
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
            for order in snapshot.razorpay_orders
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
            for payment in snapshot.razorpay_payments
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
            for refund in snapshot.razorpay_refunds
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
            for settlement in snapshot.settlements
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
            for line in snapshot.settlement_lines
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
            for credit in snapshot.bank_credits
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
                raw_payload=(
                    row.raw_payload
                    if isinstance(row.raw_payload, dict)
                    else json.loads(row.raw_payload)
                ),
            )
            for row in snapshot.malformed_rows
        ]
    )
