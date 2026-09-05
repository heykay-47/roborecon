from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import IngestionRecord
from app.common.enums import ExceptionStatus, ResultStatus
from app.common.messages import MALFORMED_RECORD_MESSAGE
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine

SUPPORTED_SOURCE_TYPES = frozenset(
    {
        "ledger",
        "razorpay_order",
        "razorpay_payment",
        "razorpay_refund",
        "settlement",
        "settlement_line",
        "bank_credit",
        "quarantine",
    }
)

_SOURCE_COLUMNS = (
    "source_type",
    "source_id",
    "reference",
    "amount",
    "currency",
    "status",
    "business_at",
    "batch_id",
    "parse_error",
    "ordering_id",
)


def _null_string():
    return cast(null(), String)


def _null_integer():
    return cast(null(), Integer)


def _null_datetime():
    return cast(null(), DateTime(timezone=True))


def _source_filters(
    model: Any,
    *,
    batch_id: UUID | None,
    source_id: UUID | None,
    status: str | None,
    status_column: Any,
) -> list[Any]:
    filters: list[Any] = []
    if batch_id is not None:
        filters.append(model.batch_id == batch_id)
    if source_id is not None:
        filters.append(model.id == source_id)
    if status is not None:
        filters.append(cast(status_column, String) == status)
    return filters


def _source_select(
    model: Any,
    source_type: str,
    *,
    reference: Any,
    amount: Any,
    currency: Any,
    status_column: Any,
    business_at: Any,
    batch_id: UUID | None,
    source_id: UUID | None,
    status: str | None,
    parse_error: Any,
) -> Any:
    return select(
        literal(source_type, type_=String).label("source_type"),
        model.id.label("source_id"),
        reference.label("reference"),
        amount.label("amount"),
        currency.label("currency"),
        cast(status_column, String).label("status"),
        business_at.label("business_at"),
        model.batch_id.label("batch_id"),
        parse_error.label("parse_error"),
        model.id.label("ordering_id"),
    ).where(
        *_source_filters(
            model,
            batch_id=batch_id,
            source_id=source_id,
            status=status,
            status_column=status_column,
        )
    )


def _source_selects(
    *,
    batch_id: UUID | None,
    source_type: str | None,
    source_id: UUID | None,
    status: str | None,
) -> list[Any]:
    selects: list[Any] = []

    if source_type in (None, "ledger"):
        selects.append(
            _source_select(
                LedgerEntry,
                "ledger",
                reference=LedgerEntry.reference,
                amount=LedgerEntry.amount,
                currency=LedgerEntry.currency,
                status_column=LedgerEntry.entry_type,
                business_at=LedgerEntry.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "razorpay_order"):
        selects.append(
            _source_select(
                RazorpayOrder,
                "razorpay_order",
                reference=RazorpayOrder.receipt,
                amount=RazorpayOrder.amount,
                currency=RazorpayOrder.currency,
                status_column=RazorpayOrder.status,
                business_at=RazorpayOrder.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "razorpay_payment"):
        selects.append(
            _source_select(
                RazorpayPayment,
                "razorpay_payment",
                reference=RazorpayPayment.provider_payment_id,
                amount=RazorpayPayment.amount,
                currency=RazorpayPayment.currency,
                status_column=RazorpayPayment.status,
                business_at=RazorpayPayment.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "razorpay_refund"):
        selects.append(
            _source_select(
                RazorpayRefund,
                "razorpay_refund",
                reference=RazorpayRefund.provider_refund_id,
                amount=RazorpayRefund.amount,
                currency=RazorpayRefund.currency,
                status_column=RazorpayRefund.status,
                business_at=RazorpayRefund.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "settlement"):
        selects.append(
            _source_select(
                Settlement,
                "settlement",
                reference=Settlement.provider_settlement_id,
                amount=Settlement.amount,
                currency=Settlement.currency,
                status_column=Settlement.status,
                business_at=Settlement.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "settlement_line"):
        selects.append(
            _source_select(
                SettlementLine,
                "settlement_line",
                reference=SettlementLine.reference,
                amount=SettlementLine.amount,
                currency=SettlementLine.currency,
                status_column=SettlementLine.line_type,
                business_at=SettlementLine.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "bank_credit"):
        selects.append(
            _source_select(
                BankCredit,
                "bank_credit",
                reference=BankCredit.utr,
                amount=BankCredit.amount,
                currency=BankCredit.currency,
                status_column=literal("credited", type_=String),
                business_at=BankCredit.business_at,
                batch_id=batch_id,
                source_id=source_id,
                status=status,
                parse_error=_null_string(),
            )
        )
    if source_type in (None, "quarantine"):
        quarantine_filters = _source_filters(
            IngestionRecord,
            batch_id=batch_id,
            source_id=None,
            status=status,
            status_column=IngestionRecord.parse_status,
        )
        if source_id is not None:
            quarantine_filters.append(false())
        selects.append(
            select(
                literal("quarantine", type_=String).label("source_type"),
                cast(null(), IngestionRecord.id.type).label("source_id"),
                _null_string().label("reference"),
                _null_integer().label("amount"),
                _null_string().label("currency"),
                IngestionRecord.parse_status.label("status"),
                _null_datetime().label("business_at"),
                IngestionRecord.batch_id.label("batch_id"),
                literal(MALFORMED_RECORD_MESSAGE, type_=String).label("parse_error"),
                IngestionRecord.id.label("ordering_id"),
            ).where(
                *quarantine_filters
            )
        )

    return selects


def _matched_state(autonomous: Any) -> Any:
    return case(
        (
            cast(ReconciliationResult.status, String) == ResultStatus.matched.value,
            case(
                (autonomous.is_(True), literal("autonomous")),
                else_=literal("matched"),
            ),
        ),
        else_=literal("unreconciled"),
    )


def _result_state() -> Any:
    return _matched_state(ReconciliationResult.autonomous)


def _link_state() -> Any:
    return _matched_state(MatchLink.autonomous)


def _exception_state() -> Any:
    status = cast(ReconciliationException.status, String)
    return case(
        (
            status.in_([status.value for status in ExceptionStatus]),
            status,
        ),
        else_=literal(ExceptionStatus.open.value),
    )


def _relationship_selects(*, batch_id: UUID | None) -> list[Any]:
    result_select = select(
        ReconciliationResult.batch_id.label("batch_id"),
        ReconciliationResult.primary_source_type.label("source_type"),
        ReconciliationResult.primary_source_id.label("source_id"),
        _result_state().label("state"),
        ReconciliationResult.run_id.label("run_id"),
        ReconciliationResult.id.label("result_id"),
        cast(null(), ReconciliationException.id.type).label("exception_id"),
        literal(1, type_=Integer).label("priority"),
        ReconciliationResult.created_at.label("candidate_created_at"),
        ReconciliationRun.started_at.label("run_started_at"),
        ReconciliationRun.created_at.label("run_created_at"),
        ReconciliationResult.id.label("candidate_id"),
    ).select_from(
        ReconciliationResult
    ).join(
        ReconciliationRun,
        and_(
            ReconciliationRun.id == ReconciliationResult.run_id,
            ReconciliationRun.batch_id == ReconciliationResult.batch_id,
        ),
    ).where(
        ReconciliationResult.primary_source_id.is_not(None),
        *(
            [ReconciliationResult.batch_id == batch_id]
            if batch_id is not None
            else []
        ),
    )

    link_select = select(
        ReconciliationResult.batch_id.label("batch_id"),
        MatchLink.source_type.label("source_type"),
        MatchLink.source_id.label("source_id"),
        _link_state().label("state"),
        ReconciliationResult.run_id.label("run_id"),
        ReconciliationResult.id.label("result_id"),
        cast(null(), ReconciliationException.id.type).label("exception_id"),
        literal(2, type_=Integer).label("priority"),
        MatchLink.created_at.label("candidate_created_at"),
        ReconciliationRun.started_at.label("run_started_at"),
        ReconciliationRun.created_at.label("run_created_at"),
        MatchLink.id.label("candidate_id"),
    ).select_from(
        MatchLink
    ).join(
        ReconciliationResult,
        MatchLink.result_id == ReconciliationResult.id,
    ).join(
        ReconciliationRun,
        and_(
            ReconciliationRun.id == ReconciliationResult.run_id,
            ReconciliationRun.batch_id == ReconciliationResult.batch_id,
        ),
    ).where(
        MatchLink.run_id == ReconciliationResult.run_id,
        MatchLink.source_id.is_not(None),
        *(
            [ReconciliationResult.batch_id == batch_id]
            if batch_id is not None
            else []
        ),
    )

    exception_result = ReconciliationResult
    direct_exception_select = select(
        ReconciliationException.batch_id.label("batch_id"),
        ReconciliationException.source_type.label("source_type"),
        ReconciliationException.source_id.label("source_id"),
        _exception_state().label("state"),
        ReconciliationException.run_id.label("run_id"),
        ReconciliationException.result_id.label("result_id"),
        ReconciliationException.id.label("exception_id"),
        literal(3, type_=Integer).label("priority"),
        ReconciliationException.created_at.label("candidate_created_at"),
        ReconciliationRun.started_at.label("run_started_at"),
        ReconciliationRun.created_at.label("run_created_at"),
        ReconciliationException.id.label("candidate_id"),
    ).select_from(
        ReconciliationException
    ).outerjoin(
        exception_result,
        exception_result.id == ReconciliationException.result_id,
    ).join(
        ReconciliationRun,
        and_(
            ReconciliationRun.id == ReconciliationException.run_id,
            ReconciliationRun.batch_id == ReconciliationException.batch_id,
        ),
    ).where(
        ReconciliationException.source_type.is_not(None),
        ReconciliationException.source_id.is_not(None),
        or_(
            ReconciliationException.result_id.is_(None),
            and_(
                exception_result.id.is_not(None),
                ReconciliationException.run_id == exception_result.run_id,
                ReconciliationException.batch_id == exception_result.batch_id,
            ),
        ),
        *(
            [ReconciliationException.batch_id == batch_id]
            if batch_id is not None
            else []
        ),
    )

    inherited_exception_primary_select = select(
        ReconciliationException.batch_id.label("batch_id"),
        ReconciliationResult.primary_source_type.label("source_type"),
        ReconciliationResult.primary_source_id.label("source_id"),
        _exception_state().label("state"),
        ReconciliationException.run_id.label("run_id"),
        ReconciliationException.result_id.label("result_id"),
        ReconciliationException.id.label("exception_id"),
        literal(3, type_=Integer).label("priority"),
        ReconciliationException.created_at.label("candidate_created_at"),
        ReconciliationRun.started_at.label("run_started_at"),
        ReconciliationRun.created_at.label("run_created_at"),
        ReconciliationException.id.label("candidate_id"),
    ).select_from(
        ReconciliationException
    ).join(
        ReconciliationResult,
        and_(
            ReconciliationException.result_id == ReconciliationResult.id,
            ReconciliationException.run_id == ReconciliationResult.run_id,
            ReconciliationException.batch_id == ReconciliationResult.batch_id,
        ),
    ).join(
        ReconciliationRun,
        and_(
            ReconciliationRun.id == ReconciliationException.run_id,
            ReconciliationRun.batch_id == ReconciliationException.batch_id,
        ),
    ).where(
        and_(
            ReconciliationException.source_type.is_(None),
            ReconciliationException.source_id.is_(None),
        ),
        ReconciliationResult.primary_source_id.is_not(None),
        *(
            [ReconciliationException.batch_id == batch_id]
            if batch_id is not None
            else []
        ),
    )

    inherited_exception_link_select = select(
        ReconciliationException.batch_id.label("batch_id"),
        MatchLink.source_type.label("source_type"),
        MatchLink.source_id.label("source_id"),
        _exception_state().label("state"),
        ReconciliationException.run_id.label("run_id"),
        ReconciliationException.result_id.label("result_id"),
        ReconciliationException.id.label("exception_id"),
        literal(3, type_=Integer).label("priority"),
        ReconciliationException.created_at.label("candidate_created_at"),
        ReconciliationRun.started_at.label("run_started_at"),
        ReconciliationRun.created_at.label("run_created_at"),
        ReconciliationException.id.label("candidate_id"),
    ).select_from(
        ReconciliationException
    ).join(
        ReconciliationResult,
        and_(
            ReconciliationException.result_id == ReconciliationResult.id,
            ReconciliationException.run_id == ReconciliationResult.run_id,
            ReconciliationException.batch_id == ReconciliationResult.batch_id,
        ),
    ).join(
        MatchLink,
        and_(
            MatchLink.result_id == ReconciliationResult.id,
            MatchLink.run_id == ReconciliationResult.run_id,
        ),
    ).join(
        ReconciliationRun,
        and_(
            ReconciliationRun.id == ReconciliationException.run_id,
            ReconciliationRun.batch_id == ReconciliationException.batch_id,
        ),
    ).where(
        and_(
            ReconciliationException.source_type.is_(None),
            ReconciliationException.source_id.is_(None),
        ),
        MatchLink.source_id.is_not(None),
        *(
            [ReconciliationException.batch_id == batch_id]
            if batch_id is not None
            else []
        ),
    )

    return [
        result_select,
        link_select,
        direct_exception_select,
        inherited_exception_primary_select,
        inherited_exception_link_select,
    ]


def _build_read_model(
    *,
    batch_id: UUID | None,
    source_type: str | None,
    source_id: UUID | None,
    status: str | None,
):
    source_records = union_all(
        *_source_selects(
            batch_id=batch_id,
            source_type=source_type,
            source_id=source_id,
            status=status,
        )
    ).cte("source_records")
    relationship_candidates = union_all(
        *_relationship_selects(batch_id=batch_id)
    ).cte(
        "relationship_candidates"
    )
    relationship_filters = []
    if source_type is not None:
        relationship_filters.append(
            relationship_candidates.c.source_type == source_type
        )
    if source_id is not None:
        relationship_filters.append(relationship_candidates.c.source_id == source_id)
    ranked_relationships = select(
        relationship_candidates,
        func.row_number()
        .over(
            partition_by=[
                relationship_candidates.c.batch_id,
                relationship_candidates.c.source_type,
                relationship_candidates.c.source_id,
            ],
            order_by=[
                func.coalesce(
                    relationship_candidates.c.run_started_at,
                    relationship_candidates.c.candidate_created_at,
                ).desc(),
                func.coalesce(
                    relationship_candidates.c.run_created_at,
                    relationship_candidates.c.candidate_created_at,
                ).desc(),
                cast(relationship_candidates.c.run_id, String).desc(),
                relationship_candidates.c.priority.desc(),
                relationship_candidates.c.candidate_created_at.desc(),
                cast(relationship_candidates.c.candidate_id, String).desc(),
            ],
        )
        .label("relationship_rank"),
    ).where(*relationship_filters).cte("ranked_relationships")
    latest_relationships = select(ranked_relationships).where(
        ranked_relationships.c.relationship_rank == 1
    ).cte("latest_relationships")
    join_condition = and_(
        source_records.c.batch_id == latest_relationships.c.batch_id,
        source_records.c.source_type == latest_relationships.c.source_type,
        source_records.c.source_id == latest_relationships.c.source_id,
    )
    return source_records, latest_relationships, source_records.outerjoin(
        latest_relationships, join_condition
    )


async def load_source_record_page(
    session: AsyncSession,
    batch_id: UUID | None,
    source_type: str | None,
    source_id: UUID | None,
    status: str | None,
    reconciliation_state: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    source_records, latest_relationships, source_with_relationships = _build_read_model(
        batch_id=batch_id,
        source_type=source_type,
        source_id=source_id,
        status=status,
    )
    state = func.coalesce(
        latest_relationships.c.state,
        literal("unreconciled", type_=String),
    )
    filters = []
    if reconciliation_state is not None:
        filters.append(state == reconciliation_state)
    query = select(
        *(
            source_records.c[column]
            for column in _SOURCE_COLUMNS[:-1]
        ),
        state.label("reconciliation_state"),
        latest_relationships.c.run_id.label("run_id"),
        latest_relationships.c.result_id.label("result_id"),
        latest_relationships.c.exception_id.label("exception_id"),
        func.count().over().label("_total_count"),
    ).select_from(source_with_relationships).where(*filters)
    query = query.order_by(
        source_records.c.business_at.asc().nulls_last(),
        source_records.c.source_type.asc(),
        source_records.c.ordering_id.asc(),
    ).offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(query)).mappings().all()

    if rows:
        total = int(rows[0]["_total_count"])
    else:
        total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(source_with_relationships)
                    .where(*filters)
                )
            ).scalar()
            or 0
        )
    records = [
        {
            column: row[column]
            for column in (
                "source_type",
                "source_id",
                "reference",
                "amount",
                "currency",
                "status",
                "business_at",
                "batch_id",
                "parse_error",
                "reconciliation_state",
                "run_id",
                "result_id",
                "exception_id",
            )
        }
        for row in rows
    ]
    return records, total
