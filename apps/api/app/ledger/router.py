from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api import ApiModel, PaginatedResponse
from app.database import get_session
from app.ledger.read_model import SUPPORTED_SOURCE_TYPES, load_source_record_page

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
    if source_type is not None and source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported source type")

    records, total = await load_source_record_page(
        session,
        batch_id,
        source_type,
        source_id,
        status,
        reconciliation_state,
        page,
        page_size,
    )
    return TransactionListResponse(
        items=[TransactionRecord.model_validate(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )
