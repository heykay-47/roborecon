from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.model import AuditEvent
from app.batch.model import Batch
from app.batch.schema import BatchResponse
from app.common.enums import AuditEventType, BatchKind, BatchStatus
from app.config import settings
from app.database import get_session
from app.demo.source_service import persist_source_records, source_counts
from app.razorpay.adapter import (
    DemoRazorpaySource,
    HttpRazorpaySource,
    RazorpayAdapterError,
    RazorpaySource,
)

router = APIRouter(prefix="/razorpay", tags=["razorpay"])


def source_from_settings() -> RazorpaySource:
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        return HttpRazorpaySource(
            settings.razorpay_key_id,
            settings.razorpay_key_secret,
            base_url=settings.razorpay_base_url,
            page_size=settings.razorpay_page_size,
            max_pages=settings.razorpay_max_pages,
            timeout=settings.razorpay_timeout_seconds,
        )
    return DemoRazorpaySource()


async def sync_snapshot(
    session: AsyncSession, source: RazorpaySource
) -> tuple[Batch, dict[str, int]]:
    """Fetch before opening the transaction so failed imports leave prior data intact."""
    try:
        snapshot = await source.fetch_snapshot()
    except (RazorpayAdapterError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay test-mode sync failed",
        ) from exc

    now = datetime.now(timezone.utc)
    counts = source_counts(snapshot)
    batch = Batch(
        id=uuid4(),
        kind=BatchKind.test_mode_sync,
        status=BatchStatus.completed,
        seed="razorpay-test-mode",
        ground_truth_available=False,
        source_row_count=counts["total"],
        started_at=now,
        completed_at=now,
    )

    async with session.begin():
        session.add(batch)
        await session.flush()
        await persist_source_records(session, snapshot, batch)
        session.add(
            AuditEvent(
                batch_id=batch.id,
                event_type=AuditEventType.razorpay_sync_started,
                sequence=1,
                actor="razorpay",
                entity_type="batch",
                entity_id=batch.id,
                occurred_at=now,
                summary="Razorpay test-mode sync started",
            )
        )
        session.add(
            AuditEvent(
                batch_id=batch.id,
                event_type=AuditEventType.razorpay_sync_completed,
                sequence=2,
                actor="razorpay",
                entity_type="batch",
                entity_id=batch.id,
                occurred_at=now,
                summary="Razorpay test-mode sync completed",
            )
        )
    return batch, counts


@router.post("/sync", response_model=BatchResponse, status_code=status.HTTP_200_OK)
async def sync_razorpay(
    session: AsyncSession = Depends(get_session),
) -> BatchResponse:
    batch, counts = await sync_snapshot(session, source_from_settings())
    response = BatchResponse.model_validate(batch)
    data = response.model_dump()
    data["source_counts"] = counts
    return BatchResponse(**data)
