from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import Batch
from app.batch.schema import BatchListResponse, BatchResponse
from app.database import get_session

router = APIRouter(tags=["batches"])


@router.get("/batches", response_model=BatchListResponse)
async def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> BatchListResponse:
    total = int(
        (await session.execute(select(func.count()).select_from(Batch))).scalar() or 0
    )
    offset = (page - 1) * page_size
    batches = (
        await session.execute(
            select(Batch)
            .order_by(Batch.created_at.desc(), Batch.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    return BatchListResponse(
        items=[BatchResponse.model_validate(batch) for batch in batches],
        total=total,
        page=page,
        page_size=page_size,
    )
