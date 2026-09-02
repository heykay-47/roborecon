from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import IngestionRecord
from app.common.api import ApiModel, PaginatedResponse
from app.database import get_session
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.settlement.model import BankCredit, Settlement

router = APIRouter(tags=["transactions"])


class TransactionRecord(ApiModel):
    source_type: str
    source_id: UUID | None
    reference: str | None
    amount: int | None
    currency: str | None
    status: str
    business_at: datetime | None
    batch_id: UUID
    reconciliation_state: str
    parse_error: str | None = None


class TransactionListResponse(PaginatedResponse[TransactionRecord]):
    pass


def _value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _record(
    *,
    source_type: str,
    source_id: UUID | None,
    reference: str | None,
    amount: int | None,
    currency: str | None,
    status: str,
    business_at: datetime | None,
    batch_id: UUID,
    parse_error: str | None = None,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "reference": reference,
        "amount": amount,
        "currency": currency,
        "status": status,
        "business_at": business_at,
        "batch_id": batch_id,
        "reconciliation_state": "unreconciled",
        "parse_error": parse_error,
    }


async def _load_source_records(
    session: AsyncSession,
    batch_id: UUID | None,
    source_type: str | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    async def load(
        model: Any,
        kind: str,
        make_record: Callable[[Any], dict[str, Any]],
    ) -> None:
        if source_type is not None and source_type != kind:
            return
        query = select(model)
        if batch_id is not None:
            query = query.where(model.batch_id == batch_id)
        result = await session.execute(query)
        records.extend(make_record(row) for row in result.scalars().all())

    await load(
        LedgerEntry,
        "ledger",
        lambda row: _record(
            source_type="ledger",
            source_id=row.id,
            reference=row.reference,
            amount=row.amount,
            currency=row.currency,
            status=_value(row.entry_type),
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        RazorpayOrder,
        "razorpay_order",
        lambda row: _record(
            source_type="razorpay_order",
            source_id=row.id,
            reference=row.receipt,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        RazorpayPayment,
        "razorpay_payment",
        lambda row: _record(
            source_type="razorpay_payment",
            source_id=row.id,
            reference=row.provider_payment_id,
            amount=row.amount,
            currency=row.currency,
            status=_value(row.status),
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        RazorpayRefund,
        "razorpay_refund",
        lambda row: _record(
            source_type="razorpay_refund",
            source_id=row.id,
            reference=row.provider_refund_id,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        Settlement,
        "settlement",
        lambda row: _record(
            source_type="settlement",
            source_id=row.id,
            reference=row.provider_settlement_id,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        BankCredit,
        "bank_credit",
        lambda row: _record(
            source_type="bank_credit",
            source_id=row.id,
            reference=row.utr,
            amount=row.amount,
            currency=row.currency,
            status="credited",
            business_at=row.business_at,
            batch_id=row.batch_id,
        ),
    )
    await load(
        IngestionRecord,
        "quarantine",
        lambda row: _record(
            source_type="quarantine",
            source_id=None,
            reference=None,
            amount=None,
            currency=None,
            status=row.parse_status,
            business_at=None,
            batch_id=row.batch_id,
            parse_error=row.parse_error,
        ),
    )
    return records


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    batch_id: UUID | None = None,
    source_type: str | None = None,
    status: str | None = None,
    reconciliation_state: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> TransactionListResponse:
    allowed_source_types = {
        "ledger",
        "razorpay_order",
        "razorpay_payment",
        "razorpay_refund",
        "settlement",
        "bank_credit",
        "quarantine",
    }
    if source_type is not None and source_type not in allowed_source_types:
        raise HTTPException(status_code=400, detail="Unsupported source type")

    records = await _load_source_records(session, batch_id, source_type)
    if status is not None:
        records = [record for record in records if record["status"] == status]
    if reconciliation_state is not None:
        records = [
            record
            for record in records
            if record["reconciliation_state"] == reconciliation_state
        ]
    records.sort(
        key=lambda record: (
            record["business_at"] is None,
            record["business_at"] or datetime.min,
            str(record["source_id"]),
        )
    )
    offset = (page - 1) * page_size
    return TransactionListResponse(
        items=[
            TransactionRecord.model_validate(record)
            for record in records[offset : offset + page_size]
        ],
        total=len(records),
        page=page,
        page_size=page_size,
    )
