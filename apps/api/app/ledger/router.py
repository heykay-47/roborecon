from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import IngestionRecord
from app.common.api import ApiModel, PaginatedResponse
from app.common.messages import MALFORMED_RECORD_MESSAGE
from app.database import get_session
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine

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
    run_id: UUID | None = None
    result_id: UUID | None = None
    exception_id: UUID | None = None


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
        "parse_error": (
            MALFORMED_RECORD_MESSAGE
            if source_type == "quarantine" or parse_error
            else None
        ),
        "run_id": None,
        "result_id": None,
        "exception_id": None,
    }


SourceKey = tuple[str, str, str]
RunSort = tuple[datetime, datetime, str]
RelationshipSort = tuple[datetime, datetime, str, int, datetime, str]

_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def _source_key(
    batch_id: UUID | str | None,
    source_type: str | None,
    source_id: UUID | str | None,
) -> SourceKey | None:
    if batch_id is None or source_type is None or source_id is None:
        return None
    return str(batch_id), source_type, str(source_id)


def _as_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return _MIN_DATETIME
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _run_sort(run_id: UUID | str, run: Any) -> RunSort:
    started_at = _as_utc(getattr(run, "started_at", None))
    created_at = _as_utc(getattr(run, "created_at", None))
    if started_at == _MIN_DATETIME:
        started_at = created_at
    return started_at, created_at, str(run_id)


def _relationship_sort(
    run_sort: RunSort,
    priority: int,
    row: Any,
) -> RelationshipSort:
    return (
        *run_sort,
        priority,
        _as_utc(getattr(row, "created_at", None)),
        str(getattr(row, "id", "")),
    )


def _attach_relationships(
    records: list[dict[str, Any]],
    results: list[Any],
    links: list[Any],
    exceptions: list[Any],
    runs: list[Any],
) -> None:
    relationships: dict[SourceKey, dict[str, Any]] = {}
    result_keys: defaultdict[str, set[SourceKey]] = defaultdict(set)
    result_by_id: dict[str, Any] = {}
    run_sorts: dict[str, RunSort] = {
        str(run.id): _run_sort(run.id, run)
        for run in runs
        if getattr(run, "id", None) is not None
    }

    def consider(
        key: SourceKey | None,
        *,
        row: Any,
        priority: int,
        state: str,
        run_id: UUID | None,
        result_id: UUID | None,
        exception_id: UUID | None,
    ) -> None:
        if key is None:
            return
        run_sort = run_sorts.get(
            str(run_id),
            _run_sort(run_id or "", row),
        )
        candidate = {
            "sort": _relationship_sort(run_sort, priority, row),
            "state": state,
            "run_id": run_id,
            "result_id": result_id,
            "exception_id": exception_id,
        }
        current = relationships.get(key)
        if current is None or candidate["sort"] > current["sort"]:
            relationships[key] = candidate

    for result in results:
        result_id = getattr(result, "id", None)
        if result_id is None:
            continue
        result_id_key = str(result_id)
        result_by_id[result_id_key] = result
        key = _source_key(
            getattr(result, "batch_id", None),
            getattr(result, "primary_source_type", None),
            getattr(result, "primary_source_id", None),
        )
        if key is not None:
            result_keys[result_id_key].add(key)
        status = _value(getattr(result, "status", ""))
        if status == "matched":
            state = "autonomous" if getattr(result, "autonomous", False) else "matched"
        else:
            state = "unreconciled"
        consider(
            key,
            row=result,
            priority=1,
            state=state,
            run_id=getattr(result, "run_id", None),
            result_id=result_id,
            exception_id=None,
        )

    for link in links:
        result_id = getattr(link, "result_id", None)
        result = result_by_id.get(str(result_id))
        if result is None:
            continue
        result_run_id = getattr(result, "run_id", None)
        link_run_id = getattr(link, "run_id", None)
        if (
            result_run_id is None
            or link_run_id is None
            or str(link_run_id) != str(result_run_id)
        ):
            continue
        key = _source_key(
            getattr(result, "batch_id", None),
            getattr(link, "source_type", None),
            getattr(link, "source_id", None),
        )
        if result_id is not None and key is not None:
            result_keys[str(result_id)].add(key)
        result_status = _value(getattr(result, "status", ""))
        link_state = (
            "autonomous"
            if result_status == "matched" and getattr(link, "autonomous", False)
            else "matched"
            if result_status == "matched"
            else "unreconciled"
        )
        consider(
            key,
            row=link,
            priority=2,
            state=link_state,
            run_id=result_run_id,
            result_id=result_id,
            exception_id=None,
        )

    for exception in exceptions:
        result_id = getattr(exception, "result_id", None)
        result = result_by_id.get(str(result_id))
        exception_run_id = getattr(exception, "run_id", None)
        if result is not None and str(exception_run_id) != str(getattr(result, "run_id", None)):
            continue
        direct_key = _source_key(
            getattr(exception, "batch_id", None),
            getattr(exception, "source_type", None),
            getattr(exception, "source_id", None),
        )
        keys = {direct_key} if direct_key is not None else result_keys.get(str(result_id), set())
        status = _value(getattr(exception, "status", "open"))
        state = status if status in {"open", "approved", "rejected"} else "open"
        for key in keys:
            consider(
                key,
                row=exception,
                priority=3,
                state=state,
                run_id=exception_run_id,
                result_id=result_id,
                exception_id=getattr(exception, "id", None),
            )

    for record in records:
        relationship = relationships.get(
            _source_key(record.get("batch_id"), record.get("source_type"), record.get("source_id"))
        )
        if relationship is not None:
            record.update(
                reconciliation_state=relationship["state"],
                run_id=relationship["run_id"],
                result_id=relationship["result_id"],
                exception_id=relationship["exception_id"],
            )


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
        SettlementLine,
        "settlement_line",
        lambda row: _record(
            source_type="settlement_line",
            source_id=row.id,
            reference=row.reference,
            amount=row.amount,
            currency=row.currency,
            status=_value(row.line_type),
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
             parse_error=MALFORMED_RECORD_MESSAGE,
        ),
    )

    result_query = select(ReconciliationResult)
    if batch_id is not None:
        result_query = result_query.where(ReconciliationResult.batch_id == batch_id)
    result_rows = (await session.execute(result_query)).scalars().all()

    run_query = select(ReconciliationRun)
    if batch_id is not None:
        run_query = run_query.where(ReconciliationRun.batch_id == batch_id)
    run_rows = (await session.execute(run_query)).scalars().all()

    link_query = select(MatchLink).join(
        ReconciliationResult,
        MatchLink.result_id == ReconciliationResult.id,
    )
    if batch_id is not None:
        link_query = link_query.where(ReconciliationResult.batch_id == batch_id)
    link_rows = (await session.execute(link_query)).scalars().all()

    exception_query = select(ReconciliationException)
    if batch_id is not None:
        exception_query = exception_query.where(ReconciliationException.batch_id == batch_id)
    exception_rows = (await session.execute(exception_query)).scalars().all()

    _attach_relationships(records, result_rows, link_rows, exception_rows, run_rows)
    return records


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    batch_id: UUID | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
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
        "settlement_line",
        "bank_credit",
        "quarantine",
    }
    if source_type is not None and source_type not in allowed_source_types:
        raise HTTPException(status_code=400, detail="Unsupported source type")

    records = await _load_source_records(session, batch_id, source_type)
    if source_id is not None:
        records = [record for record in records if record["source_id"] == source_id]
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
