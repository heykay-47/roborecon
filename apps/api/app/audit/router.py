from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import list_events
from app.common.enums import AuditEventType
from app.database import get_session
from app.reconciliation.schema import AuditEventListResponse, AuditEventResponse

router = APIRouter(tags=["audit"])


@router.get("/audit-events", response_model=AuditEventListResponse)
async def get_audit_events(
    batch_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    event_type: AuditEventType | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> AuditEventListResponse:
    rows, total = await list_events(
        session,
        batch_id=batch_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
