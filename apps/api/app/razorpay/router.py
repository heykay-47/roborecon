from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit_service
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
    """Persist one isolated source batch with explicit success/failure lifecycle."""
    started_at = datetime.now(timezone.utc)
    batch = Batch(
        id=uuid4(),
        kind=BatchKind.test_mode_sync,
        status=BatchStatus.running,
        seed="razorpay-test-mode",
        ground_truth_available=False,
        source_row_count=0,
        started_at=started_at,
    )

    async with session.begin():
        session.add(batch)
        await session.flush()
        await audit_service.append_event(
            session,
            batch_id=batch.id,
            event_type=AuditEventType.razorpay_sync_started,
            actor="razorpay",
            entity_type="batch",
            entity_id=batch.id,
            summary="Razorpay test-mode sync started",
        )

    async def mark_failed() -> None:
        failed_at = datetime.now(timezone.utc)
        async with session.begin():
            batch.status = BatchStatus.failed
            batch.completed_at = failed_at
            await audit_service.append_event(
                session,
                batch_id=batch.id,
                event_type=AuditEventType.razorpay_sync_failed,
                actor="razorpay",
                entity_type="batch",
                entity_id=batch.id,
                summary="Razorpay test-mode sync failed",
            )

    try:
        snapshot = await source.fetch_snapshot()
    except (RazorpayAdapterError, OSError) as exc:
        await mark_failed()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay test-mode sync failed",
        ) from exc

    try:
        counts = source_counts(snapshot)
        completed_at = datetime.now(timezone.utc)
        async with session.begin():
            await persist_source_records(session, snapshot, batch)
            batch.status = BatchStatus.completed
            batch.source_row_count = counts["total"]
            batch.completed_at = completed_at
            await audit_service.append_event(
                session,
                batch_id=batch.id,
                event_type=AuditEventType.razorpay_sync_completed,
                actor="razorpay",
                entity_type="batch",
                entity_id=batch.id,
                summary="Razorpay test-mode sync completed",
            )
    except Exception as exc:
        await mark_failed()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay test-mode sync failed",
        ) from exc
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
