from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch.model import Batch
from app.common.enums import RunStatus
from app.database import get_session
from app.evaluation.service import evaluate_run
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.reconciliation.schema import (
    ExceptionResponse,
    MatchLinkResponse,
    ReconciliationMetricsResponse,
    ReconciliationResultResponse,
    ReconciliationRunListResponse,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
)
from app.reconciliation.service import RunAlreadyRunning, run_reconciliation


router = APIRouter(prefix="/reconciliation-runs", tags=["reconciliation-runs"])
metrics_router = APIRouter(tags=["metrics"])


def _result_response(result: ReconciliationResult) -> ReconciliationResultResponse:
    return ReconciliationResultResponse.model_validate(result)


def _link_response(link: MatchLink) -> MatchLinkResponse:
    return MatchLinkResponse.model_validate(link)


def _exception_response(
    exception: ReconciliationException,
) -> ExceptionResponse:
    return ExceptionResponse.model_validate(exception)


async def _run_response(
    session: AsyncSession,
    run: ReconciliationRun,
    *,
    include_detail: bool,
) -> ReconciliationRunResponse:
    batch = await session.get(Batch, run.batch_id)
    if batch is None:
        raise HTTPException(status_code=500, detail="Reconciliation batch is missing")
    results: list[ReconciliationResultResponse] = []
    links: list[MatchLinkResponse] = []
    exceptions: list[ExceptionResponse] = []
    if include_detail:
        result_rows = (
            await session.execute(
                select(ReconciliationResult)
                .where(ReconciliationResult.run_id == run.id)
                .order_by(ReconciliationResult.created_at, ReconciliationResult.id)
            )
        ).scalars().all()
        link_rows = (
            await session.execute(
                select(MatchLink)
                .where(MatchLink.run_id == run.id)
                .order_by(MatchLink.created_at, MatchLink.id)
            )
        ).scalars().all()
        exception_rows = (
            await session.execute(
                select(ReconciliationException)
                .where(ReconciliationException.run_id == run.id)
                .order_by(ReconciliationException.created_at, ReconciliationException.id)
            )
        ).scalars().all()
        results = [_result_response(row) for row in result_rows]
        links = [_link_response(row) for row in link_rows]
        exceptions = [_exception_response(row) for row in exception_rows]
    return ReconciliationRunResponse(
        id=run.id,
        batch_id=run.batch_id,
        batch_kind=batch.kind,
        status=run.status,
        source_row_count=run.source_row_count,
        source_counts=run.source_counts or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        throughput=run.throughput,
        metrics=(
            run.metrics
            if run.metrics is not None
            else None
        ),
        error_message=run.error_message,
        results=results,
        links=links,
        exceptions=exceptions,
    )


async def _evaluate_if_needed(
    session: AsyncSession,
    run: ReconciliationRun,
) -> None:
    run_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    if run_status == RunStatus.completed.value and run.metrics is None:
        await evaluate_run(session, run.id)


@router.post(
    "",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reconciliation_run(
    request: ReconciliationRunRequest,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationRunResponse:
    try:
        run = await run_reconciliation(session, request.batch_id)
    except RunAlreadyRunning as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500, detail="Reconciliation failed before completion"
        ) from error
    await _evaluate_if_needed(session, run)
    return await _run_response(session, run, include_detail=True)


@router.get("", response_model=ReconciliationRunListResponse)
async def list_reconciliation_runs(
    batch_id: UUID | None = None,
    run_status: RunStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> ReconciliationRunListResponse:
    query = select(ReconciliationRun)
    count_query = select(func.count()).select_from(ReconciliationRun)
    if batch_id is not None:
        query = query.where(ReconciliationRun.batch_id == batch_id)
        count_query = count_query.where(ReconciliationRun.batch_id == batch_id)
    if run_status is not None:
        query = query.where(ReconciliationRun.status == run_status)
        count_query = count_query.where(ReconciliationRun.status == run_status)
    total = int((await session.execute(count_query)).scalar() or 0)
    offset = (page - 1) * page_size
    rows = (
        await session.execute(
            query.order_by(ReconciliationRun.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    return ReconciliationRunListResponse(
        items=[await _run_response(session, row, include_detail=False) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=ReconciliationRunResponse)
async def get_reconciliation_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationRunResponse:
    run = await session.get(ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    await _evaluate_if_needed(session, run)
    return await _run_response(session, run, include_detail=True)


@router.get(
    "/{run_id}/metrics",
    response_model=ReconciliationMetricsResponse,
)
async def get_reconciliation_metrics(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationMetricsResponse:
    run = await session.get(ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    await _evaluate_if_needed(session, run)
    if run.metrics is None:
        raise HTTPException(status_code=409, detail="Run metrics are not available")
    return ReconciliationMetricsResponse(run_id=run.id, **run.metrics)


async def _latest_run(
    session: AsyncSession,
    run_id: UUID | None,
) -> ReconciliationRun:
    if run_id is not None:
        run = await session.get(ReconciliationRun, run_id)
    else:
        run = (
            await session.execute(
                select(ReconciliationRun)
                .where(ReconciliationRun.status == RunStatus.completed)
                .order_by(ReconciliationRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="No completed reconciliation run found")
    return run


@metrics_router.get("/metrics", response_model=ReconciliationMetricsResponse)
async def get_latest_metrics(
    run_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> ReconciliationMetricsResponse:
    run = await _latest_run(session, run_id)
    await _evaluate_if_needed(session, run)
    if run.metrics is None:
        raise HTTPException(status_code=409, detail="Run metrics are not available")
    return ReconciliationMetricsResponse(run_id=run.id, **run.metrics)
