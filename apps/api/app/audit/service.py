from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.model import AuditEvent
from app.batch.model import Batch
from app.common.enums import AuditEventType

_GLOBAL_AUDIT_LOCK_KEY = 2_147_483_647


async def append_event(
    session: AsyncSession,
    *,
    batch_id: UUID | None,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: UUID | None,
    summary: str,
    actor: str = "system",
    source_type: str | None = None,
    source_id: UUID | None = None,
    tool_trace: dict[str, Any] | None = None,
) -> AuditEvent:
    if batch_id is not None:
        batch = (
            await session.execute(
                select(Batch)
                .where(Batch.id == batch_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if batch is None:
            raise ValueError("Audit batch was not found")
    else:
        await session.execute(
            select(func.pg_advisory_xact_lock(_GLOBAL_AUDIT_LOCK_KEY))
        )
    query = select(func.coalesce(func.max(AuditEvent.sequence), 0))
    if batch_id is None:
        query = query.where(AuditEvent.batch_id.is_(None))
    else:
        query = query.where(AuditEvent.batch_id == batch_id)
    sequence = (await session.execute(query)).scalar_one()
    event = AuditEvent(
        batch_id=batch_id,
        event_type=event_type,
        sequence=int(sequence or 0) + 1,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        source_type=source_type,
        source_id=source_id,
        occurred_at=datetime.now(timezone.utc),
        summary=summary,
        tool_trace=tool_trace,
    )
    session.add(event)
    return event


async def list_events(
    session: AsyncSession,
    *,
    batch_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEvent], int]:
    filters = []
    if batch_id is not None:
        filters.append(AuditEvent.batch_id == batch_id)
    if entity_type is not None:
        filters.append(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditEvent.entity_id == entity_id)
    count_query = select(func.count()).select_from(AuditEvent).where(*filters)
    total = int((await session.execute(count_query)).scalar() or 0)
    query = (
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.occurred_at, AuditEvent.sequence, AuditEvent.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(query)).scalars().all()
    return rows, total
