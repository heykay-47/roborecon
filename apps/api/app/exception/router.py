from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.exception.service import (
    InvalidReviewCandidate,
    ReviewConflict,
    ReviewNotFound,
    get_exception_detail,
    review_exception,
)
from app.reconciliation.model import ReconciliationException
from app.reconciliation.schema import (
    ExceptionDetailResponse,
    ExceptionListResponse,
    ExceptionResponse,
    ReviewDecision,
    ReviewRequest,
)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("", response_model=ExceptionListResponse)
async def list_exceptions(
    batch_id: UUID | None = None,
    exception_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> ExceptionListResponse:
    filters = []
    if batch_id is not None:
        filters.append(ReconciliationException.batch_id == batch_id)
    if exception_status is not None:
        filters.append(ReconciliationException.status == exception_status)
    total = int(
        (await session.execute(
            select(func.count()).select_from(ReconciliationException).where(*filters)
        )).scalar()
        or 0
    )
    rows = (
        await session.execute(
            select(ReconciliationException)
            .where(*filters)
            .order_by(ReconciliationException.created_at, ReconciliationException.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return ExceptionListResponse(
        items=[ExceptionResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{exception_id}", response_model=ExceptionDetailResponse)
async def get_exception(
    exception_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExceptionDetailResponse:
    try:
        return await get_exception_detail(session, exception_id)
    except ReviewNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/{exception_id}/review",
    response_model=ReviewDecision,
    status_code=status.HTTP_200_OK,
)
async def review_exception_endpoint(
    exception_id: UUID,
    request: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewDecision:
    try:
        return await review_exception(
            session,
            exception_id,
            request.action,
            request.candidate_id,
            request.note,
            request.actor,
        )
    except ReviewNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReviewConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except InvalidReviewCandidate as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
