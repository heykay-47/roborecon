from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model import (
    MAX_SOURCE_IDS_PER_CALL,
    MAX_TOOL_ROUNDS,
    AIInvestigation,
    Citation,
    InvestigationContext,
    InvestigationMode,
    ProviderRecommendation,
    ToolRequest,
    ToolResult,
)
from app.ai.provider import (
    InvestigationProvider,
    ProviderError,
    configured_providers,
)
from app.ai.tools import (
    CrossBatchSourceError,
    ToolError,
    ToolExecutor,
    UnknownToolError,
)
from app.audit.model import AuditEvent
from app.common.enums import AuditEventType, ExceptionStatus, RunStatus
from app.reconciliation.model import (
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)

_ALLOWED_TOOLS = {
    "get_run_metrics",
    "get_exception_evidence",
    "get_settlement_breakdown",
    "get_source_records",
}

_ERROR_MESSAGES = {
    "provider_unavailable": "No configured AI provider was available.",
    "timeout": "The AI provider timed out.",
    "rate_limited": "The AI provider rate limit was reached.",
    "malformed_response": "The AI provider returned an invalid response.",
    "unknown_tool": "The AI provider requested a tool that is not allowed.",
    "cross_batch_source": "The AI provider requested a source outside this batch.",
    "source_id_limit": "The AI provider requested too many source IDs.",
    "tool_round_limit": "The AI provider exceeded the tool round limit.",
    "invalid_citation": "The AI provider returned an invalid citation.",
    "tool_error": "A read-only investigation tool rejected the request.",
}


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _exception_context(
    exception: ReconciliationException,
    run: ReconciliationRun,
    result: ReconciliationResult | None,
) -> InvestigationContext:
    allowed: list[UUID] = []
    references: list[Citation] = []

    def add_reference(source_type: str | None, value: Any) -> None:
        source_id = _as_uuid(value)
        if source_id is None or source_id in allowed:
            return
        allowed.append(source_id)
        references.append(Citation(source_type=source_type or "source", source_id=source_id))

    add_reference(exception.source_type, exception.source_id)
    if result is not None:
        add_reference(result.primary_source_type, result.primary_source_id)
        for selected_id in result.selected_ids or []:
            add_reference(None, selected_id)
        for candidate in result.candidates or []:
            if isinstance(candidate, Mapping):
                add_reference(None, candidate.get("candidate_id"))

    evidence = result.evidence if result is not None and result.evidence else []
    return InvestigationContext(
        exception_id=exception.id,
        batch_id=exception.batch_id,
        run_id=exception.run_id,
        exception_type=exception.exception_type,
        exception_message=exception.message,
        amount=exception.amount,
        deterministic_status=(
            getattr(result.status, "value", result.status) if result is not None else None
        ),
        deterministic_evidence=evidence,
        allowed_source_ids=allowed,
        source_references=references,
    )


def _provider_name(provider: Any) -> str:
    return str(getattr(provider, "name", provider.__class__.__name__.lower()))[:100]


def _provider_model(provider: Any) -> str | None:
    value = getattr(provider, "model", None)
    return str(value)[:150] if value is not None else None


def _normalise_recommendation(raw: Any, provider: Any) -> ProviderRecommendation:
    provider_name = _provider_name(provider)
    provider_model = _provider_model(provider) or "unknown"
    if isinstance(raw, ProviderRecommendation):
        recommendation = raw
    elif isinstance(raw, Mapping):
        payload = dict(raw)
        if "tool" in payload:
            recommendation = ProviderRecommendation(
                tool_request=ToolRequest(
                    tool=payload["tool"],
                    arguments=payload.get("arguments", {}),
                    call_id=payload.get("call_id"),
                )
            )
        elif "tool_request" in payload:
            recommendation = ProviderRecommendation.model_validate(payload)
        else:
            recommendation = ProviderRecommendation.model_validate(payload)
    else:
        raise ProviderError(provider_name, provider_model, "malformed_response")
    if recommendation.tool_request is None and not recommendation.recommendation.strip():
        raise ProviderError(provider_name, provider_model, "malformed_response")
    return recommendation


def _error_code(error: BaseException, provider: Any) -> str:
    if isinstance(error, ProviderError):
        return error.code
    if isinstance(error, UnknownToolError):
        return "unknown_tool"
    if isinstance(error, CrossBatchSourceError):
        return "cross_batch_source"
    if isinstance(error, ToolError):
        if "maximum tool rounds" in str(error).lower():
            return "tool_round_limit"
        if "too many source ids" in str(error).lower():
            return "source_id_limit"
        return "tool_error"
    if isinstance(error, (TimeoutError,)):
        return "timeout"
    return "malformed_response"


def _safe_tool_trace(
    *,
    round_number: int,
    request: ToolRequest,
    status: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "round": round_number,
        "tool": request.tool[:100],
        "status": status,
    }
    raw_ids = request.arguments.get("source_ids", request.arguments.get("sourceIds", []))
    if isinstance(raw_ids, list):
        trace["sourceIds"] = [str(item)[:80] for item in raw_ids[:MAX_SOURCE_IDS_PER_CALL]]
    if error_code is not None:
        trace["error"] = error_code
    return trace


def _normalise_tool_result(name: str, raw: Any) -> ToolResult:
    if isinstance(raw, ToolResult):
        return raw
    if isinstance(raw, Mapping) and "citations" in raw:
        citations = [Citation.model_validate(item) for item in raw.get("citations", [])]
        data = {key: value for key, value in raw.items() if key != "citations"}
        return ToolResult(tool=name, data=data, citations=citations)
    return ToolResult(tool=name, data=raw)


def _valid_citations(
    recommendation: ProviderRecommendation,
    context: InvestigationContext,
) -> bool:
    if not recommendation.citations:
        return False
    valid = {
        (citation.source_type, citation.source_id)
        for citation in context.source_references
    }
    valid_ids = set(context.allowed_source_ids)
    for result in context.tool_results:
        valid.update((citation.source_type, citation.source_id) for citation in result.citations)
        valid_ids.update(citation.source_id for citation in result.citations)
    return all(
        (citation.source_type, citation.source_id) in valid
        or citation.source_id in valid_ids
        for citation in recommendation.citations
    )


async def _run_provider(
    provider: InvestigationProvider,
    context: InvestigationContext,
    tools: Any,
    trace: list[dict[str, Any]],
) -> ProviderRecommendation:
    active_context = context
    for round_number in range(1, MAX_TOOL_ROUNDS + 1):
        recommendation = _normalise_recommendation(
            await provider.investigate(active_context), provider
        )
        request = recommendation.tool_request
        if request is None:
            if not _valid_citations(recommendation, active_context):
                raise ProviderError(
                    _provider_name(provider),
                    _provider_model(provider) or "unknown",
                    "invalid_citation",
                )
            trace.append(
                {
                    "provider": _provider_name(provider),
                    "model": _provider_model(provider),
                    "status": "recommendation",
                }
            )
            return recommendation
        if request.tool not in _ALLOWED_TOOLS:
            trace.append(
                _safe_tool_trace(
                    round_number=round_number,
                    request=request,
                    status="rejected",
                    error_code="unknown_tool",
                )
            )
            raise UnknownToolError(f"Tool is not allowed: {request.tool}")
        raw_ids = request.arguments.get(
            "source_ids", request.arguments.get("sourceIds", [])
        )
        if isinstance(raw_ids, list) and len(raw_ids) > MAX_SOURCE_IDS_PER_CALL:
            trace.append(
                _safe_tool_trace(
                    round_number=round_number,
                    request=request,
                    status="rejected",
                    error_code="source_id_limit",
                )
            )
            raise ToolError("Too many source IDs")
        try:
            raw_result = await tools.execute(request.tool, request.arguments, active_context)
            tool_result = _normalise_tool_result(request.tool, raw_result)
        except Exception as error:
            trace.append(
                _safe_tool_trace(
                    round_number=round_number,
                    request=request,
                    status="rejected",
                    error_code=_error_code(error, provider),
                )
            )
            raise
        trace.append(
            _safe_tool_trace(round_number=round_number, request=request, status="completed")
        )
        history = list(active_context.history)
        history.append(
            {
                "role": "model",
                "callId": request.call_id or f"round-{round_number}",
                "functionCall": {"name": request.tool, "args": request.arguments},
            }
        )
        history.append(
            {
                "role": "tool",
                "callId": request.call_id or f"round-{round_number}",
                "name": request.tool,
                "content": tool_result.data,
            }
        )
        active_context = active_context.model_copy(
            update={
                "history": history,
                "tool_results": [*active_context.tool_results, tool_result],
            }
        )
        if round_number == MAX_TOOL_ROUNDS:
            raise ToolError("Maximum tool rounds exceeded")
    raise ToolError("Maximum tool rounds exceeded")


def _fallback(
    context: InvestigationContext,
    *,
    error_code: str | None,
    trace: list[dict[str, Any]],
    provider: str | None = None,
    model: str | None = None,
) -> AIInvestigation:
    status = context.deterministic_status or context.exception_type
    return AIInvestigation(
        investigation_id=uuid4(),
        exception_id=context.exception_id,
        run_id=context.run_id,
        batch_id=context.batch_id,
        mode=InvestigationMode.deterministic_fallback,
        provider=provider,
        model=model,
        recommendation=(
            f"Deterministic reconciliation remains authoritative for {status}; "
            "review the persisted evidence and candidate records."
        ),
        confidence=0,
        citations=context.source_references,
        tool_trace=trace,
        error_code=error_code,
        error_message=_ERROR_MESSAGES.get(error_code) if error_code else None,
    )


async def _persist(
    session: AsyncSession,
    investigation: AIInvestigation,
) -> AIInvestigation:
    from app.ai.model import AIInvestigationRecord

    record = AIInvestigationRecord(
        id=investigation.investigation_id,
        exception_id=investigation.exception_id,
        run_id=investigation.run_id,
        batch_id=investigation.batch_id,
        mode=investigation.mode.value,
        provider=investigation.provider,
        model=investigation.model,
        recommendation=investigation.recommendation,
        confidence=investigation.confidence,
        citations=[item.model_dump(mode="json") for item in investigation.citations],
        tool_trace=investigation.tool_trace,
        error_code=investigation.error_code,
        error_message=investigation.error_message,
    )
    session.add(record)
    await session.flush()
    return investigation


async def _audit_investigation(
    session: AsyncSession,
    investigation: AIInvestigation,
) -> None:
    try:
        sequence = (
            await session.execute(
                select(func.coalesce(func.max(AuditEvent.sequence), 0)).where(
                    AuditEvent.batch_id == investigation.batch_id
                )
            )
        ).scalar()
        next_sequence = int(sequence or 0) + 1
        for trace in investigation.tool_trace:
            if trace.get("tool") is None:
                continue
            session.add(
                AuditEvent(
                    batch_id=investigation.batch_id,
                    event_type=AuditEventType.ai_tool_called,
                    sequence=next_sequence,
                    actor="ai",
                    entity_type="reconciliation_exception",
                    entity_id=investigation.exception_id,
                    occurred_at=datetime.now(timezone.utc),
                    summary=f"AI read-only tool {trace.get('tool', 'unknown')} called",
                    tool_trace=trace,
                )
            )
            next_sequence += 1
        session.add(
            AuditEvent(
                batch_id=investigation.batch_id,
                event_type=AuditEventType.ai_recommendation,
                sequence=next_sequence,
                actor="ai",
                entity_type="reconciliation_exception",
                entity_id=investigation.exception_id,
                occurred_at=datetime.now(timezone.utc),
                summary="AI advisory recommendation recorded",
                tool_trace={
                    "mode": investigation.mode.value,
                    "provider": investigation.provider,
                    "model": investigation.model,
                    "error": investigation.error_code,
                    "citations": [
                        item.model_dump(mode="json") for item in investigation.citations
                    ],
                },
            )
        )
    except Exception:
        # AI audit persistence is advisory and must never alter the exception outcome.
        return


async def investigate_exception(
    session: AsyncSession,
    exception_id: UUID,
    provider: InvestigationProvider | None = None,
    tools: ToolExecutor | None = None,
) -> AIInvestigation:
    exception = await session.get(ReconciliationException, exception_id)
    if exception is None:
        raise ValueError("Reconciliation exception was not found")
    run = await session.get(ReconciliationRun, exception.run_id)
    if run is None or run.batch_id != exception.batch_id:
        raise ValueError("Reconciliation run is not part of the exception batch")
    result = (
        await session.get(ReconciliationResult, exception.result_id)
        if exception.result_id is not None
        else None
    )
    context = _exception_context(exception, run, result)
    executor = tools or ToolExecutor(session, context)
    providers: list[InvestigationProvider] = (
        [provider] if provider is not None else configured_providers()
    )
    trace: list[dict[str, Any]] = []
    last_error: str | None = "provider_unavailable" if not providers else None
    selected_provider: str | None = None
    selected_model: str | None = None
    for candidate in providers:
        selected_provider = _provider_name(candidate)
        selected_model = _provider_model(candidate)
        try:
            recommendation = await _run_provider(candidate, context, executor, trace)
            investigation = AIInvestigation(
                investigation_id=uuid4(),
                exception_id=context.exception_id,
                run_id=context.run_id,
                batch_id=context.batch_id,
                mode=InvestigationMode.provider,
                provider=selected_provider,
                model=selected_model,
                recommendation=recommendation.recommendation,
                confidence=recommendation.confidence,
                citations=recommendation.citations,
                tool_trace=trace,
            )
            await _persist(session, investigation)
            await _audit_investigation(session, investigation)
            return investigation
        except Exception as error:
            last_error = _error_code(error, candidate)
            trace.append(
                {
                    "provider": selected_provider,
                    "model": selected_model,
                    "status": "failed",
                    "error": last_error,
                }
            )

    investigation = _fallback(
        context,
        error_code=last_error,
        trace=trace,
        provider=selected_provider,
        model=selected_model,
    )
    await _persist(session, investigation)
    await _audit_investigation(session, investigation)
    return investigation


def _risk_class(exception: Any) -> str | None:
    value = str(getattr(exception, "exception_type", "")).lower().replace("-", "_")
    message = str(getattr(exception, "message", "")).lower()
    combined = f"{value} {message}"
    if "duplicate" in combined:
        return "duplicate"
    if "refund" in combined:
        return "refund"
    if any(token in combined for token in ("hold", "held", "release", "released")):
        return "held_released_settlement"
    if any(token in combined for token in ("fuzzy", "ambiguous", "reference")):
        return "fuzzy_reference"
    if any(token in combined for token in ("mismatch", "discrepancy", "net")):
        return "net_discrepancy"
    return None


def select_exception_portfolio(exceptions: Iterable[Any]) -> list[Any]:
    """Select one highest-paise open exception per requested risk class."""
    selected: dict[str, Any] = {}
    for exception in exceptions:
        status = getattr(
            getattr(exception, "status", None),
            "value",
            getattr(exception, "status", None),
        )
        if status is not None and status != ExceptionStatus.open.value:
            continue
        risk_class = _risk_class(exception)
        if risk_class is None:
            continue
        current = selected.get(risk_class)
        amount = int(getattr(exception, "amount", 0) or 0)
        current_amount = int(getattr(current, "amount", 0) or 0) if current else -1
        if current is None or amount > current_amount:
            selected[risk_class] = exception
    return [
        selected[risk_class]
        for risk_class in (
            "fuzzy_reference",
            "duplicate",
            "refund",
            "held_released_settlement",
            "net_discrepancy",
        )
        if risk_class in selected
    ]


async def investigate_completed_run(
    session: AsyncSession,
    run_id: UUID,
    provider: InvestigationProvider | None = None,
) -> list[AIInvestigation]:
    """Create the bounded investigation portfolio after a completed run commits."""
    run = await session.get(ReconciliationRun, run_id)
    run_status = getattr(run.status, "value", run.status) if run is not None else None
    if run is None or run_status != RunStatus.completed.value:
        return []
    rows = (
        await session.execute(
            select(ReconciliationException)
            .where(
                ReconciliationException.run_id == run_id,
                ReconciliationException.status == ExceptionStatus.open,
            )
            .order_by(ReconciliationException.amount.desc(), ReconciliationException.id)
        )
    ).scalars().all()
    investigations = [
        await investigate_exception(session, exception.id, provider=provider)
        for exception in select_exception_portfolio(rows)
    ]
    if investigations:
        await session.commit()
    return investigations
