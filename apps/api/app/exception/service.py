from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model import AIInvestigationRecord
from app.audit import service as audit_service
from app.audit.model import AuditEvent
from app.common.enums import AuditEventType, ExceptionStatus, ResultStatus, ReviewAction
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.reconciliation.model import (
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.reconciliation.schema import (
    AIInvestigationResponse,
    AuditEventResponse,
    ExceptionDetailResponse,
    ExceptionResponse,
    ReconciliationResultResponse,
    ReviewDecision,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine


class ReviewNotFound(ValueError):
    pass


class ReviewConflict(ValueError):
    pass


class InvalidReviewCandidate(ValueError):
    pass


@asynccontextmanager
async def _transaction(session: AsyncSession):
    transaction = session.begin()
    if inspect.isawaitable(transaction):
        transaction = await transaction
        try:
            yield
        except Exception:
            await transaction.rollback()
            raise
        else:
            await transaction.commit()
        return
    async with transaction:
        yield


_SOURCE_MODELS: tuple[tuple[str, type[Any]], ...] = (
    ("ledger", LedgerEntry),
    ("razorpay_order", RazorpayOrder),
    ("razorpay_payment", RazorpayPayment),
    ("razorpay_refund", RazorpayRefund),
    ("settlement", Settlement),
    ("settlement_line", SettlementLine),
    ("bank_credit", BankCredit),
)


def _value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _source_summary(source_type: str, row: Any) -> dict[str, Any]:
    values = {
        column.name: _value(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name not in {"batch_id", "disabled_at", "created_at", "updated_at"}
    }
    return {"sourceType": source_type, **values}


def _candidate_row(result: ReconciliationResult, candidate_id: UUID) -> dict[str, Any] | None:
    for candidate in result.candidates or []:
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("candidate_id", candidate.get("candidateId"))
        if str(value) == str(candidate_id):
            return candidate
    return None


def _candidate_source_key(candidate: Any) -> tuple[str | None, UUID] | None:
    if not isinstance(candidate, dict):
        return None
    raw_id = candidate.get("candidate_id", candidate.get("candidateId"))
    if not raw_id:
        return None
    try:
        candidate_id = UUID(str(raw_id))
    except (TypeError, ValueError):
        return None
    return (
        candidate.get("source_type", candidate.get("sourceType")),
        candidate_id,
    )


async def _find_source(
    session: AsyncSession,
    *,
    batch_id: UUID,
    source_id: UUID,
    source_type: str | None = None,
) -> tuple[str, Any] | None:
    models = (
        item for item in _SOURCE_MODELS if source_type is None or item[0] == source_type
    )
    for current_type, model in models:
        row = (
            await session.execute(
                select(model).where(model.id == source_id, model.batch_id == batch_id)
            )
        ).scalars().first()
        if row is not None:
            return current_type, row
    return None


def _adjust_metrics(
    metrics: dict[str, Any] | None,
    *,
    action: ReviewAction,
    amount: int | None,
    stage: str | None = None,
) -> None:
    if not isinstance(metrics, dict):
        return

    aliases = {
        "open_exceptions": ("open_exceptions", "openExceptions"),
        "financially_unresolved_cases": (
            "financially_unresolved_cases",
            "financiallyUnresolvedCases",
        ),
        "money_reconciled": ("money_reconciled", "moneyReconciled"),
        "money_unresolved": ("money_unresolved", "moneyUnresolved"),
    }

    def increment(name: str, delta: int) -> None:
        for key in aliases[name]:
            if key in metrics and metrics[key] is not None:
                metrics[key] = max(0, int(metrics[key]) + delta)

    increment("open_exceptions", -1)
    if action is ReviewAction.approve:
        increment("financially_unresolved_cases", -1)
        increment("money_reconciled", amount or 0)
        increment("money_unresolved", -(amount or 0))
    review_adjusted = metrics.setdefault("review_adjusted", {})
    if not isinstance(review_adjusted, dict):
        review_adjusted = {}
        metrics["review_adjusted"] = review_adjusted
    review_adjusted["closedCases"] = int(review_adjusted.get("closedCases", 0)) + 1
    review_adjusted["reviewedCases"] = int(review_adjusted.get("reviewedCases", 0)) + 1
    key = "approvedCases" if action is ReviewAction.approve else "rejectedCases"
    review_adjusted[key] = int(review_adjusted.get(key, 0)) + 1
    if action is ReviewAction.approve:
        review_adjusted["resolvedCases"] = int(
            review_adjusted.get("resolvedCases", 0)
        ) + 1
        if "matchable_cases" in metrics and metrics["matchable_cases"]:
            review_adjusted["matchRate"] = round(
                int(review_adjusted["resolvedCases"])
                * 100
                / int(metrics["matchable_cases"]),
                2,
            )
        money_reconciled = review_adjusted.get("moneyReconciled")
        if money_reconciled is not None:
            review_adjusted["moneyReconciled"] = int(money_reconciled) + (
                amount or 0
            )
    stage_metrics = metrics.get("stage_metrics", metrics.get("stageMetrics"))
    if isinstance(stage_metrics, dict) and stage in stage_metrics:
        stage_metric = stage_metrics[stage]
        if isinstance(stage_metric, dict):
            if "open_exceptions" in stage_metric:
                stage_metric["open_exceptions"] = max(
                    0, int(stage_metric["open_exceptions"]) - 1
                )
            if "openExceptions" in stage_metric:
                stage_metric["openExceptions"] = max(
                    0, int(stage_metric["openExceptions"]) - 1
                )
            if action is ReviewAction.approve:
                if "unresolved_cases" in stage_metric:
                    stage_metric["unresolved_cases"] = max(
                        0, int(stage_metric["unresolved_cases"]) - 1
                    )
                if "unresolvedCases" in stage_metric:
                    stage_metric["unresolvedCases"] = max(
                        0, int(stage_metric["unresolvedCases"]) - 1
                    )


async def review_exception(
    session: AsyncSession,
    exception_id: UUID,
    action: ReviewAction | str,
    candidate_id: UUID | str | None,
    note: str | None,
    actor: str,
) -> ReviewDecision:
    action = ReviewAction(action)
    candidate_uuid = UUID(str(candidate_id)) if candidate_id is not None else None
    reviewed_at = datetime.now(timezone.utc)
    link_id: UUID | None = None

    async with _transaction(session):
        exception = (
            await session.execute(
                select(ReconciliationException)
                .where(ReconciliationException.id == exception_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if exception is None:
            raise ReviewNotFound("Reconciliation exception was not found")
        if getattr(exception.status, "value", exception.status) != ExceptionStatus.open.value:
            raise ReviewConflict("Reconciliation exception has already been reviewed")

        result = None
        candidate_source = None
        if exception.result_id is not None:
            result = await session.get(ReconciliationResult, exception.result_id)
            if result is None or (
                result.batch_id != exception.batch_id or result.run_id != exception.run_id
            ):
                raise InvalidReviewCandidate("Exception result is outside its batch")
        if action is ReviewAction.approve:
            if result is None or candidate_uuid is None:
                raise InvalidReviewCandidate(
                    "Approve requires a candidate from the exception result"
                )
            candidate = _candidate_row(result, candidate_uuid)
            if candidate is None:
                raise InvalidReviewCandidate(
                    "Candidate is not part of the exception result"
                )
            candidate_source = await _find_source(
                session,
                batch_id=exception.batch_id,
                source_id=candidate_uuid,
                source_type=candidate.get("source_type", candidate.get("sourceType")),
            )
            if candidate_source is None:
                raise InvalidReviewCandidate(
                    "Candidate is not a source record in the exception batch"
                )
            if candidate_source[1].batch_id != exception.batch_id:
                raise InvalidReviewCandidate(
                    "Candidate is not a source record in the exception batch"
                )

        if action is ReviewAction.reject and result is not None:
            existing_links = (
                await session.execute(
                    select(MatchLink)
                    .where(MatchLink.result_id == result.id)
                    .with_for_update()
                )
            ).scalars().all()
            for link in existing_links:
                if link.actor == "system" and link.role != "human_approved":
                    await session.delete(link)

        exception.status = (
            ExceptionStatus.approved
            if action is ReviewAction.approve
            else ExceptionStatus.rejected
        )
        exception.review_note = note
        exception.reviewed_by = actor
        exception.reviewed_at = reviewed_at
        if action is ReviewAction.reject and result is not None:
            result.status = ResultStatus.confirmed_no_match
        if action is ReviewAction.approve:
            source_type, source = candidate_source
            link = MatchLink(
                run_id=exception.run_id,
                result_id=exception.result_id,
                source_type=source_type,
                source_id=source.id,
                role="human_approved",
                autonomous=False,
                actor=actor,
            )
            session.add(link)
            await session.flush()
            link_id = link.id

        run = (
            await session.execute(
                select(ReconciliationRun)
                .where(ReconciliationRun.id == exception.run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is not None:
            updated_metrics = deepcopy(run.metrics)
            _adjust_metrics(
                updated_metrics,
                action=action,
                amount=exception.amount,
                stage=(
                    result.stage.value
                    if result is not None and hasattr(result.stage, "value")
                    else str(result.stage)
                    if result is not None
                    else None
                ),
            )
            run.metrics = updated_metrics
            from app.reconciliation.close_brief import mark_latest_brief_stale

            await mark_latest_brief_stale(session, run.id, reviewed_at)
        audit_source_type = (
            candidate_source[0]
            if candidate_source is not None
            else exception.source_type
        )
        audit_source_id = (
            candidate_source[1].id
            if candidate_source is not None
            else exception.source_id
        )
        await audit_service.append_event(
            session,
            batch_id=exception.batch_id,
            event_type=(
                AuditEventType.review_approved
                if action is ReviewAction.approve
                else AuditEventType.review_rejected
            ),
            entity_type="reconciliation_exception",
            entity_id=exception.id,
            actor=actor,
            source_type=audit_source_type,
            source_id=audit_source_id,
            summary=(
                "Exception approved by human review"
                if action is ReviewAction.approve
                else "Exception rejected by human review"
            ),
            tool_trace={"note": note} if note else None,
        )

    return ReviewDecision(
        id=exception.id,
        result_id=exception.result_id,
        action=action,
        status=exception.status,
        candidate_id=candidate_uuid,
        note=exception.review_note,
        actor=actor,
        reviewed_at=exception.reviewed_at or reviewed_at,
        link_id=link_id,
    )


async def _get_exception(
    session: AsyncSession,
    exception_id: UUID,
) -> ReconciliationException | None:
    return (
        await session.execute(
            select(ReconciliationException).where(
                ReconciliationException.id == exception_id
            )
        )
    ).scalar_one_or_none()


async def get_exception_detail(
    session: AsyncSession,
    exception_id: UUID,
) -> ExceptionDetailResponse:
    exception = await _get_exception(session, exception_id)
    if exception is None:
        raise ReviewNotFound("Reconciliation exception was not found")
    result = (
        await session.get(ReconciliationResult, exception.result_id)
        if exception.result_id is not None
        else None
    )
    link_rows = []
    if result is not None:
        link_rows = (
            await session.execute(
                select(MatchLink)
                .where(MatchLink.result_id == result.id)
                .order_by(MatchLink.created_at, MatchLink.id)
            )
        ).scalars().all()
    source_summaries: list[dict[str, Any]] = []
    source_keys: list[tuple[str | None, UUID | None]] = []
    if exception.source_id is not None:
        source_keys.append((exception.source_type, exception.source_id))
    if result is not None:
        source_keys.extend((link.source_type, link.source_id) for link in link_rows)
        for item in result.selected_ids or []:
            if not item:
                continue
            try:
                source_keys.append((None, UUID(str(item))))
            except (TypeError, ValueError):
                continue
        for candidate in result.candidates or []:
            source_key = _candidate_source_key(candidate)
            if source_key is not None:
                source_keys.append(source_key)
    seen: set[UUID] = set()
    for source_type, source_id in source_keys:
        if source_id in seen:
            continue
        seen.add(source_id)
        source = await _find_source(
            session,
            batch_id=exception.batch_id,
            source_id=source_id,
            source_type=source_type,
        )
        if source is not None:
            source_summaries.append(_source_summary(*source))

    investigations = (
        await session.execute(
            select(AIInvestigationRecord)
            .where(AIInvestigationRecord.exception_id == exception.id)
            .order_by(AIInvestigationRecord.created_at, AIInvestigationRecord.id)
        )
    ).scalars().all()
    audit_events = (
        await session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.batch_id == exception.batch_id,
                AuditEvent.entity_id == exception.id,
            )
            .order_by(AuditEvent.occurred_at, AuditEvent.sequence, AuditEvent.id)
        )
    ).scalars().all()
    criterion_evidence = result.evidence if result is not None else []
    arithmetic: dict[str, Any] = {
        "amount": result.amount if result is not None else exception.amount,
        "currency": result.currency if result is not None else None,
        "score": result.score if result is not None else None,
        "runnerUpScore": result.runner_up_score if result is not None else None,
        "margin": result.margin if result is not None else None,
        "observations": [
            item.get("observed_values", item.get("observedValues", {}))
            for item in criterion_evidence
            if item.get("observed_values", item.get("observedValues"))
        ],
    }
    exception_response = ExceptionResponse.model_validate(exception).model_copy(
        update={
            "ai_ready": (
                getattr(exception.status, "value", exception.status)
                == ExceptionStatus.open.value
                and not investigations
            )
        }
    )
    return ExceptionDetailResponse(
        **exception_response.model_dump(),
        result=(
            None
            if result is None
            else ReconciliationResultResponse.model_validate(result)
        ),
        source_summaries=source_summaries,
        criterion_evidence=criterion_evidence,
        arithmetic=arithmetic,
        ai_investigations=[AIInvestigationResponse.model_validate(item) for item in investigations],
        audit_events=[AuditEventResponse.model_validate(item) for item in audit_events],
    )
