from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.investigator import sanitize_actor
from app.ai.model import (
    BatchCloseCitation,
    BatchCloseContext,
    BatchCloseExceptionContext,
    BatchCloseProviderResponse,
    BatchCloseProviderTheme,
)
from app.ai.provider import BatchCloseProvider, ProviderError, configured_providers
from app.ai.provider import provider_model as _provider_model
from app.ai.provider import provider_name as _provider_name
from app.audit import service as audit_service
from app.common.enums import (
    AuditEventType,
    CloseBriefMode,
    ClosePosture,
    ExceptionStatus,
    ReconciliationStage,
)
from app.config import settings
from app.reconciliation.model import (
    BatchCloseBrief,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.reconciliation.schema import (
    BatchCloseAICoverageResponse,
    BatchCloseBriefResponse,
    BatchCloseCitationResponse,
    BatchCloseCoverageResponse,
    BatchCloseReviewActionResponse,
    BatchCloseThemeResponse,
)

_GENERATION_STATUS = "generating"
_COMPLETED_STATUS = "completed"
_ERROR_MESSAGES = {
    "provider_unavailable": "No configured AI provider was available.",
    "timeout": "The AI provider timed out.",
    "rate_limited": "The AI provider rate limit was reached.",
    "malformed_response": "The AI provider returned an invalid response.",
    "invalid_citation": "The AI provider returned an invalid citation.",
    "incomplete_coverage": "The AI provider did not cover every open exception.",
    "request_error": "The AI provider could not be reached.",
    "input_limit": "The Batch Close AI input exceeded the configured size limit.",
}


class CloseBriefNotFound(ValueError):
    pass


class CloseBriefConflict(ValueError):
    pass


class CloseBriefValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "incomplete_coverage"):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CloseBriefDraft:
    mode: CloseBriefMode
    provider: str | None
    model: str | None
    themes: list[BatchCloseProviderTheme]
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class _Snapshot:
    run: ReconciliationRun
    results: list[ReconciliationResult]
    exceptions: list[ReconciliationException]
    context: BatchCloseContext
    captured_at: datetime


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _status(value: Any) -> str:
    return str(_value(value))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique_strings(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if value is not None and str(value)})


def _evidence_codes(result: ReconciliationResult | None) -> tuple[list[str], list[str]]:
    if result is None:
        return [], []
    rule_codes: list[Any] = []
    contradictions: list[Any] = []
    for evidence in result.evidence or []:
        if isinstance(evidence, dict):
            rule_codes.append(evidence.get("rule_code", evidence.get("ruleCode")))
    for candidate in result.candidates or []:
        if isinstance(candidate, dict):
            contradictions.extend(candidate.get("contradictions", []))
    return _unique_strings(rule_codes), _unique_strings(contradictions)


def _result_summary(result: ReconciliationResult) -> dict[str, Any]:
    rule_codes, contradiction_codes = _evidence_codes(result)
    return {
        "resultId": str(result.id),
        "stage": _value(result.stage),
        "status": _value(result.status),
        "amount": result.amount,
        "currency": result.currency,
        "score": result.score,
        "margin": result.margin,
        "autonomous": result.autonomous,
        "ruleCodes": rule_codes,
        "contradictionCodes": contradiction_codes,
    }


def _exception_amount(
    exception: ReconciliationException,
    results_by_id: dict[UUID, ReconciliationResult],
) -> int:
    amount = exception.amount
    if amount is None and exception.result_id is not None:
        result = results_by_id.get(exception.result_id)
        amount = result.amount if result is not None else None
    return abs(_safe_int(amount))


def _money_totals(
    results: list[ReconciliationResult],
    exceptions: list[ReconciliationException],
) -> tuple[int, int]:
    results_by_id = {result.id: result for result in results}
    unresolved_result_ids: set[UUID] = set()
    unresolved_exception_ids: set[UUID] = set()
    money_unresolved = 0
    for exception in exceptions:
        if _status(exception.status) == ExceptionStatus.approved.value:
            continue
        if exception.result_id is not None:
            if exception.result_id in unresolved_result_ids:
                continue
            unresolved_result_ids.add(exception.result_id)
        elif exception.id in unresolved_exception_ids:
            continue
        unresolved_exception_ids.add(exception.id)
        money_unresolved += _exception_amount(exception, results_by_id)

    approved_result_ids = {
        exception.result_id
        for exception in exceptions
        if _status(exception.status) == ExceptionStatus.approved.value
        and exception.result_id is not None
    }
    money_reconciled = sum(
        abs(_safe_int(result.amount))
        for result in results
        if result.id not in unresolved_result_ids
        and _status(result.stage) == ReconciliationStage.ledger_to_razorpay.value
        and (_status(result.status) == "matched" or result.id in approved_result_ids)
    )
    return money_reconciled, money_unresolved


def _operational_metrics(run: ReconciliationRun) -> dict[str, Any]:
    metrics = run.metrics if isinstance(run.metrics, dict) else {}
    aliases = {
        "recordsProcessed": ("records_processed", "recordsProcessed"),
        "durationMs": ("duration_ms", "durationMs"),
        "throughput": ("throughput",),
        "sourceThroughput": ("source_throughput", "sourceThroughput"),
        "settlementNet": ("settlement_net", "settlementNet"),
    }
    values: dict[str, Any] = {}
    for output_name, names in aliases.items():
        for name in names:
            if name in metrics:
                values[output_name] = metrics[name]
                break
    return values


def _exception_citations(exception: ReconciliationException) -> list[BatchCloseCitation]:
    return [
        BatchCloseCitation(
            exception_id=exception.id,
            source_type=exception.source_type,
            source_id=exception.source_id,
        )
    ]


def _build_context(
    run: ReconciliationRun,
    results: list[ReconciliationResult],
    exceptions: list[ReconciliationException],
) -> BatchCloseContext:
    results_by_id = {result.id: result for result in results}
    money_reconciled, money_unresolved = _money_totals(results, exceptions)
    open_exceptions = [
        exception
        for exception in exceptions
        if _status(exception.status) == ExceptionStatus.open.value
    ]
    open_exceptions.sort(
        key=lambda exception: (
            -_exception_amount(exception, results_by_id),
            str(exception.exception_type),
            str(exception.id),
        )
    )
    exception_contexts = []
    for exception in open_exceptions:
        result = results_by_id.get(exception.result_id)
        rule_codes, contradiction_codes = _evidence_codes(result)
        exception_contexts.append(
            BatchCloseExceptionContext(
                exception_id=exception.id,
                exception_type=exception.exception_type,
                stage=_value(result.stage) if result is not None else None,
                status=_status(exception.status),
                amount=_exception_amount(exception, results_by_id),
                message=exception.message,
                rule_codes=rule_codes,
                contradiction_codes=contradiction_codes,
                citations=_exception_citations(exception),
            )
        )
    return BatchCloseContext(
        run_id=run.id,
        batch_id=run.batch_id,
        source_row_count=_safe_int(run.source_row_count),
        result_count=len(results),
        money_reconciled=money_reconciled,
        money_unresolved=money_unresolved,
        operational_metrics=_operational_metrics(run),
        source_counts=run.source_counts or {},
        result_summaries=[_result_summary(result) for result in results],
        open_exceptions=exception_contexts,
    )


async def _load_snapshot(
    session: AsyncSession,
    run: ReconciliationRun,
) -> _Snapshot:
    results = list(
        (
            await session.execute(
                select(ReconciliationResult)
                .where(
                    ReconciliationResult.run_id == run.id,
                    ReconciliationResult.batch_id == run.batch_id,
                )
                .order_by(ReconciliationResult.created_at, ReconciliationResult.id)
            )
        )
        .scalars()
        .all()
    )
    exceptions = list(
        (
            await session.execute(
                select(ReconciliationException)
                .where(
                    ReconciliationException.run_id == run.id,
                    ReconciliationException.batch_id == run.batch_id,
                )
                .order_by(ReconciliationException.created_at, ReconciliationException.id)
            )
        )
        .scalars()
        .all()
    )
    return _Snapshot(
        run=run,
        results=results,
        exceptions=exceptions,
        context=_build_context(run, results, exceptions),
        captured_at=datetime.now(timezone.utc),
    )


def _humanize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


def _fallback_key(exception: BatchCloseExceptionContext) -> tuple[str, str, str]:
    code = (
        exception.contradiction_codes[0]
        if exception.contradiction_codes
        else exception.rule_codes[0]
        if exception.rule_codes
        else "general"
    )
    return exception.exception_type, exception.stage or "unknown", code


def build_deterministic_fallback(
    context: BatchCloseContext,
    *,
    error_code: str,
    provider: str | None = None,
    model: str | None = None,
) -> CloseBriefDraft:
    grouped: dict[tuple[str, str, str], list[BatchCloseExceptionContext]] = defaultdict(list)
    for exception in context.open_exceptions:
        grouped[_fallback_key(exception)].append(exception)
    themes: list[BatchCloseProviderTheme] = []
    for exception_type, stage, code in sorted(grouped):
        rows = grouped[(exception_type, stage, code)]
        ids = [row.exception_id for row in rows]
        title = f"{_humanize(exception_type)} in {_humanize(stage)}"
        themes.append(
            BatchCloseProviderTheme(
                title=title,
                summary=(
                    f"{len(rows)} open exception(s) share the {code} signal in this "
                    "reconciliation stage."
                ),
                exception_ids=ids,
                review_action=(
                    "Review each cited Exception against its persisted source evidence "
                    "before close review."
                ),
                citations=[citation for row in rows for citation in row.citations]
                or [BatchCloseCitation(exception_id=ids[0])],
            )
        )
    return CloseBriefDraft(
        mode=CloseBriefMode.deterministic_fallback,
        provider=provider,
        model=model,
        themes=themes,
        error_code=error_code,
        error_message=_ERROR_MESSAGES.get(
            error_code, "The AI provider could not produce a valid response."
        ),
    )


def validate_provider_response(
    response: BatchCloseProviderResponse | Any,
    context: BatchCloseContext,
) -> BatchCloseProviderResponse:
    try:
        validated = BatchCloseProviderResponse.model_validate(response)
    except Exception as error:
        raise CloseBriefValidationError(
            "Provider response has invalid coverage or shape.",
            code="malformed_response",
        ) from error

    expected = {exception.exception_id for exception in context.open_exceptions}
    context_by_id = {exception.exception_id: exception for exception in context.open_exceptions}
    seen: set[UUID] = set()
    for theme in validated.themes:
        theme_ids = list(theme.exception_ids)
        if len(theme_ids) != len(set(theme_ids)):
            raise CloseBriefValidationError("Provider response has duplicate coverage.")
        if any(exception_id not in expected for exception_id in theme_ids):
            raise CloseBriefValidationError("Provider response has out-of-run coverage.")
        for exception_id in theme_ids:
            if exception_id in seen:
                raise CloseBriefValidationError("Provider response has duplicate coverage.")
            seen.add(exception_id)
        for citation in theme.citations:
            if citation.exception_id not in theme_ids:
                raise CloseBriefValidationError(
                    "Provider response has a citation outside its theme.",
                    code="invalid_citation",
                )
            if citation.source_id is None:
                continue
            allowed = context_by_id[citation.exception_id].citations
            if not any(
                item.source_id == citation.source_id
                and item.source_type == citation.source_type
                for item in allowed
            ):
                raise CloseBriefValidationError(
                    "Provider response has an invalid citation.",
                    code="invalid_citation",
                )
    if seen != expected:
        raise CloseBriefValidationError("Provider response has incomplete coverage.")
    return validated


def _theme_risk(exception_type: str) -> int:
    return {
        "amount_mismatch": 5,
        "duplicate": 4,
        "missing_settlement": 4,
        "missing_bank_credit": 4,
        "ambiguous": 3,
        "malformed": 2,
    }.get(exception_type, 1)


def _citation_key(citation: BatchCloseCitation) -> tuple[UUID, str | None, UUID | None]:
    return citation.exception_id, citation.source_type, citation.source_id


def _citation_payload(citation: BatchCloseCitation) -> dict[str, Any]:
    payload: dict[str, Any] = {"exception_id": str(citation.exception_id)}
    if citation.source_type is not None:
        payload["source_type"] = citation.source_type
    if citation.source_id is not None:
        payload["source_id"] = str(citation.source_id)
    return payload


def _server_themes(
    context: BatchCloseContext,
    provider_themes: list[BatchCloseProviderTheme],
) -> list[dict[str, Any]]:
    exception_by_id = {
        exception.exception_id: exception for exception in context.open_exceptions
    }
    prepared: list[tuple[tuple[Any, ...], BatchCloseProviderTheme, int, list[dict[str, Any]]]] = []
    for theme in provider_themes:
        rows = [exception_by_id[exception_id] for exception_id in theme.exception_ids]
        exposure = sum(row.amount for row in rows)
        risk = max((_theme_risk(row.exception_type) for row in rows), default=0)
        citations: list[BatchCloseCitation] = list(theme.citations)
        present = {_citation_key(citation) for citation in citations}
        for row in rows:
            for citation in row.citations or [BatchCloseCitation(exception_id=row.exception_id)]:
                if _citation_key(citation) not in present:
                    citations.append(citation)
                    present.add(_citation_key(citation))
        prepared.append(
            (
                (-exposure, -len(rows), -risk, theme.title.lower()),
                theme,
                exposure,
                [_citation_payload(citation) for citation in citations],
            )
        )
    prepared.sort(key=lambda item: item[0])
    themes: list[dict[str, Any]] = []
    for priority, (_, theme, exposure, citations) in enumerate(prepared, start=1):
        themes.append(
            {
                "theme_id": f"theme-{priority}",
                "title": theme.title,
                "summary": theme.summary,
                "exception_ids": [str(exception_id) for exception_id in theme.exception_ids],
                "exception_count": len(theme.exception_ids),
                "money_exposure": exposure,
                "priority": priority,
                "review_action": theme.review_action,
                "citations": citations,
            }
        )
    return themes


async def _generate_draft(
    context: BatchCloseContext,
    provider: BatchCloseProvider | None,
) -> CloseBriefDraft:
    if not context.open_exceptions:
        return CloseBriefDraft(
            mode=CloseBriefMode.not_required,
            provider=None,
            model=None,
            themes=[],
        )
    if len(context.prompt()) > settings.ai_max_batch_close_prompt_chars:
        return build_deterministic_fallback(context, error_code="input_limit")
    providers = [provider] if provider is not None else configured_providers()
    if not providers:
        return build_deterministic_fallback(context, error_code="provider_unavailable")

    candidate = providers[0]
    selected_provider = _provider_name(candidate)
    selected_model = _provider_model(candidate)
    try:
        response = await candidate.assess_batch_close(context)
        validated = validate_provider_response(response, context)
        return CloseBriefDraft(
            mode=CloseBriefMode.provider,
            provider=selected_provider,
            model=selected_model,
            themes=validated.themes,
        )
    except CloseBriefValidationError as error:
        last_error = error.code
    except Exception as error:
        last_error = (
            error.code
            if isinstance(error, ProviderError)
            else "timeout"
            if isinstance(error, TimeoutError)
            else "malformed_response"
        )
    return build_deterministic_fallback(
        context,
        error_code=last_error,
        provider=selected_provider,
        model=selected_model,
    )


def _artifact(
    snapshot: _Snapshot,
    draft: CloseBriefDraft,
    *,
    duration_ms: int,
) -> dict[str, Any]:
    context = snapshot.context
    open_exception_count = len(context.open_exceptions)
    posture = (
        ClosePosture.ready
        if open_exception_count == 0 and context.money_unresolved == 0
        else ClosePosture.review_required
    )
    themes = _server_themes(context, draft.themes)
    ai_exception_count = (
        open_exception_count if draft.mode is CloseBriefMode.provider else 0
    )
    review_plan = [
        {
            "priority": theme["priority"],
            "action": theme["review_action"],
            "exception_ids": theme["exception_ids"],
            "citations": theme["citations"],
        }
        for theme in themes
    ]
    citations: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for citation in [
        citation
        for theme in themes
        for citation in theme["citations"]
    ]:
        key = (
            citation.get("exception_id"),
            citation.get("source_type"),
            citation.get("source_id"),
        )
        if key not in seen:
            seen.add(key)
            citations.append(citation)
    return {
        "posture": posture.value,
        "mode": draft.mode.value,
        "provider": draft.provider,
        "model": draft.model,
        "source_row_count": context.source_row_count,
        "result_count": context.result_count,
        "open_exception_count": open_exception_count,
        "ai_exception_count": ai_exception_count,
        "money_reconciled": context.money_reconciled,
        "money_unresolved": context.money_unresolved,
        "financial_records_changed": 0,
        "deterministic_coverage": {
            "source_rows": context.source_row_count,
            "results": context.result_count,
            "open_exceptions": open_exception_count,
        },
        "ai_coverage": {
            "open_exceptions": open_exception_count,
            "covered_exceptions": ai_exception_count,
        },
        "themes": themes,
        "review_plan": review_plan,
        "citations": citations,
        "generation_duration_ms": duration_ms,
        "error_code": draft.error_code,
        "error_message": draft.error_message,
    }


async def _start_assessment(
    session: AsyncSession,
    run_id: UUID,
    actor: str,
) -> tuple[UUID, _Snapshot]:
    async with session.begin():
        run = (
            await session.execute(
                select(ReconciliationRun)
                .where(ReconciliationRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise CloseBriefNotFound("Reconciliation run not found")
        if _status(run.status) != "completed":
            raise CloseBriefConflict("Only completed reconciliation runs can be assessed")
        pending = (
            await session.execute(
                select(BatchCloseBrief)
                .where(
                    BatchCloseBrief.run_id == run.id,
                    BatchCloseBrief.generation_status == _GENERATION_STATUS,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise CloseBriefConflict("A close brief is already being generated")
        snapshot = await _load_snapshot(session, run)
        brief = BatchCloseBrief(
            run_id=run.id,
            batch_id=run.batch_id,
            generation_status=_GENERATION_STATUS,
            posture=ClosePosture.review_required.value,
            mode="pending",
            actor=actor,
            source_row_count=snapshot.context.source_row_count,
            result_count=snapshot.context.result_count,
            open_exception_count=len(snapshot.context.open_exceptions),
            ai_exception_count=len(snapshot.context.open_exceptions),
            money_reconciled=snapshot.context.money_reconciled,
            money_unresolved=snapshot.context.money_unresolved,
            deterministic_coverage={},
            ai_coverage={},
            themes=[],
            review_plan=[],
            citations=[],
        )
        session.add(brief)
        await session.flush()
        return brief.id, snapshot


def _apply_artifact(
    brief: BatchCloseBrief,
    artifact: dict[str, Any],
    *,
    actor: str,
    generated_at: datetime,
) -> None:
    brief.generation_status = _COMPLETED_STATUS
    brief.posture = artifact["posture"]
    brief.mode = artifact["mode"]
    brief.provider = artifact["provider"]
    brief.model = artifact["model"]
    brief.actor = actor
    brief.source_row_count = artifact["source_row_count"]
    brief.result_count = artifact["result_count"]
    brief.open_exception_count = artifact["open_exception_count"]
    brief.ai_exception_count = artifact["ai_exception_count"]
    brief.money_reconciled = artifact["money_reconciled"]
    brief.money_unresolved = artifact["money_unresolved"]
    brief.financial_records_changed = artifact["financial_records_changed"]
    brief.deterministic_coverage = artifact["deterministic_coverage"]
    brief.ai_coverage = artifact["ai_coverage"]
    brief.themes = artifact["themes"]
    brief.review_plan = artifact["review_plan"]
    brief.citations = artifact["citations"]
    brief.generation_duration_ms = artifact["generation_duration_ms"]
    brief.error_code = artifact["error_code"]
    brief.error_message = artifact["error_message"]
    brief.generated_at = generated_at


async def assess_batch_close(
    session: AsyncSession,
    run_id: UUID,
    *,
    actor: str = "human",
    provider: BatchCloseProvider | None = None,
) -> BatchCloseBrief:
    actor = sanitize_actor(actor, fallback="human")
    brief_id, snapshot = await _start_assessment(session, run_id, actor)
    started_ticks = perf_counter_ns()
    draft = await _generate_draft(snapshot.context, provider)
    duration_ms = max(0, round((perf_counter_ns() - started_ticks) / 1_000_000))
    artifact = _artifact(snapshot, draft, duration_ms=duration_ms)
    generated_at = datetime.now(timezone.utc)
    async with session.begin():
        run = (
            await session.execute(
                select(ReconciliationRun)
                .where(ReconciliationRun.id == snapshot.run.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise CloseBriefNotFound("Reconciliation run was not found")
        brief = await session.get(BatchCloseBrief, brief_id)
        if brief is None:
            raise CloseBriefNotFound("Batch Close Brief was not found")
        _apply_artifact(brief, artifact, actor=actor, generated_at=generated_at)
        latest_reviewed_at = (
            await session.execute(
                select(func.max(ReconciliationException.reviewed_at)).where(
                    ReconciliationException.run_id == brief.run_id,
                    ReconciliationException.batch_id == brief.batch_id,
                )
            )
        ).scalar_one()
        if latest_reviewed_at is not None and latest_reviewed_at >= snapshot.captured_at:
            brief.stale_at = latest_reviewed_at
        await audit_service.append_event(
            session,
            batch_id=brief.batch_id,
            event_type=AuditEventType.batch_close_brief_generated,
            entity_type="reconciliation_run",
            entity_id=brief.run_id,
            actor=actor,
            summary=(
                f"Batch Close Brief generated: {brief.posture} via {brief.mode}; "
                f"{brief.ai_exception_count}/{brief.open_exception_count} open exceptions "
                "covered; 0 financial records changed"
            ),
            tool_trace={
                "posture": brief.posture,
                "mode": brief.mode,
                "provider": brief.provider,
                "model": brief.model,
                "sourceRows": brief.source_row_count,
                "results": brief.result_count,
                "openExceptions": brief.open_exception_count,
                "aiExceptions": brief.ai_exception_count,
                "themeCount": len(brief.themes),
                "errorCode": brief.error_code,
                "financialRecordsChanged": 0,
            },
        )
        await session.flush()
        return brief


async def latest_close_brief(
    session: AsyncSession,
    run_id: UUID,
) -> BatchCloseBrief | None:
    return (
        await session.execute(
            select(BatchCloseBrief)
            .where(
                BatchCloseBrief.run_id == run_id,
                BatchCloseBrief.generation_status == _COMPLETED_STATUS,
            )
            .order_by(
                BatchCloseBrief.generated_at.desc(),
                BatchCloseBrief.created_at.desc(),
                BatchCloseBrief.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def mark_latest_brief_stale(
    session: AsyncSession,
    run_id: UUID,
    stale_at: datetime | None = None,
) -> None:
    brief = (
        await session.execute(
            select(BatchCloseBrief)
            .where(
                BatchCloseBrief.run_id == run_id,
                BatchCloseBrief.generation_status == _COMPLETED_STATUS,
            )
            .order_by(
                BatchCloseBrief.generated_at.desc(),
                BatchCloseBrief.created_at.desc(),
                BatchCloseBrief.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if brief is not None and brief.stale_at is None:
        brief.stale_at = stale_at or datetime.now(timezone.utc)


def close_brief_response(brief: BatchCloseBrief) -> BatchCloseBriefResponse:
    generated_at = brief.generated_at or brief.created_at or datetime.now(timezone.utc)
    return BatchCloseBriefResponse(
        brief_id=brief.id,
        run_id=brief.run_id,
        batch_id=brief.batch_id,
        posture=brief.posture,
        deterministic_coverage=BatchCloseCoverageResponse.model_validate(
            brief.deterministic_coverage or {}
        ),
        ai_coverage=BatchCloseAICoverageResponse.model_validate(brief.ai_coverage or {}),
        money_reconciled=brief.money_reconciled,
        money_unresolved=brief.money_unresolved,
        open_exceptions=brief.open_exception_count,
        financial_records_changed=brief.financial_records_changed,
        mode=brief.mode,
        provider=brief.provider,
        model=brief.model,
        themes=[BatchCloseThemeResponse.model_validate(theme) for theme in brief.themes or []],
        review_plan=[
            BatchCloseReviewActionResponse.model_validate(action)
            for action in brief.review_plan or []
        ],
        citations=[
            BatchCloseCitationResponse.model_validate(citation)
            for citation in brief.citations or []
        ],
        generated_at=generated_at,
        stale=brief.stale_at is not None,
        stale_at=brief.stale_at,
        duration_ms=brief.generation_duration_ms,
        error_code=brief.error_code,
        error_message=brief.error_message,
        actor=brief.actor,
    )
