from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.investigator import investigate_exception, sanitize_actor
from app.ai.model import AIInvestigationRecord
from app.common.enums import ExceptionStatus
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
    AIInvestigationResponse,
    ExceptionDetailResponse,
    ExceptionListResponse,
    ExceptionResponse,
    InvestigationRequest,
    ReviewDecision,
    ReviewRequest,
)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


def _exception_response(
    exception: ReconciliationException,
    *,
    ai_ready: bool,
) -> ExceptionResponse:
    return ExceptionResponse.model_validate(exception).model_copy(
        update={"ai_ready": ai_ready}
    )


@router.get("", response_model=ExceptionListResponse)
async def list_exceptions(
    batch_id: UUID | None = None,
    run_id: UUID | None = None,
    exception_type: str | None = Query(default=None, alias="type"),
    exception_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> ExceptionListResponse:
    filters = []
    if batch_id is not None:
        filters.append(ReconciliationException.batch_id == batch_id)
    if run_id is not None:
        filters.append(ReconciliationException.run_id == run_id)
    if exception_type is not None:
        filters.append(ReconciliationException.exception_type == exception_type)
    if exception_status is not None:
        filters.append(ReconciliationException.status == exception_status)
    total = int(
        (await session.execute(
            select(func.count()).select_from(ReconciliationException).where(*filters)
        )).scalar()
        or 0
    )
    investigation_exists = select(AIInvestigationRecord.id).where(
        AIInvestigationRecord.exception_id == ReconciliationException.id
    ).exists()
    ai_ready = and_(
        ReconciliationException.status == ExceptionStatus.open,
        ~investigation_exists,
    )
    rows = (
        await session.execute(
            select(ReconciliationException, ai_ready.label("ai_ready"))
            .where(*filters)
            .order_by(
                case(
                    (ReconciliationException.status == ExceptionStatus.open, 0),
                    else_=1,
                ),
                case((ai_ready, 0), else_=1),
                func.coalesce(ReconciliationException.amount, 0).desc(),
                ReconciliationException.exception_type,
                ReconciliationException.created_at,
                ReconciliationException.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ExceptionListResponse(
        items=[
            _exception_response(exception, ai_ready=bool(is_ai_ready))
            for exception, is_ai_ready in rows
        ],
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


@router.post(
    "/{exception_id}/investigate",
    response_model=AIInvestigationResponse,
    status_code=status.HTTP_200_OK,
)
async def investigate_exception_endpoint(
    exception_id: UUID,
    request: InvestigationRequest,
    session: AsyncSession = Depends(get_session),
) -> AIInvestigationResponse:
    try:
        investigation = await investigate_exception(
            session,
            exception_id,
            actor=sanitize_actor(request.actor, fallback="human"),
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail="The advisory investigation could not be persisted",
        ) from error
    return AIInvestigationResponse.model_validate(
        investigation.model_dump(mode="json")
    )
