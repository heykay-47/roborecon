from __future__ import annotations

import re
from collections.abc import Mapping
from inspect import isawaitable
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model import (
    Citation,
    InvestigationContext,
    InvestigationMode,
    ProviderRecommendation,
    ToolResult,
)
from app.ai.provider import ProviderError, configured_providers
from app.ai.tools import ToolError, ToolExecutor
from app.common.api import ApiModel
from app.reconciliation.model import ReconciliationRun
from app.settlement.model import Settlement

_DANGEROUS_REQUEST = re.compile(
    r"\b(?:sql|select|insert|update|delete|drop|alter|truncate|write|mutat(?:e|ion)|"
    r"hidden|secret|password|database|execute|jailbreak)\b",
    re.IGNORECASE,
)
_INJECTION_REQUEST = re.compile(
    r"(?:"
    r"\b(?:ignore|disregard|forget)\b[\s\S]{0,80}\b"
    r"(?:previous|prior|earlier|instructions?|rules?|prompt|message)\b"
    r"|\boverride\b[\s\S]{0,80}\b"
    r"(?:system|developer|instructions?|rules?|prompt|message)\b"
    r"|\b(?:follow|override)\b[\s\S]{0,80}\b"
    r"(?:the\s+)?(?:new\s+)?(?:system|developer)\b[\s\S]{0,40}\b"
    r"(?:instructions?|rules?|prompt|message)\b"
    r"|\bdo\s+not\s+follow\b[\s\S]{0,80}\b"
    r"(?:system|developer|instructions?|rules?|prompt|message)\b"
    r"|\bact\s+as\s+(?:an?\s+|the\s+)?"
    r"(?:system|developer|admin(?:istrator)?|root|unrestricted|different|new|other)\b"
    r"|\byou\s+are\s+now\b"
    r"|\b(?:impersonate|impersonating|pretend\s+to\s+be|pose\s+as)\b"
    r"|\b(?:reveal|show|print|repeat|expose)\b[\s\S]{0,80}\b"
    r"(?:system|developer)\s+(?:prompt|message|instructions?)\b"
    r"|\bsystem\s+prompt\b"
    r"|\breveal\s+instructions\b"
    r"|\bshow\s+all\s+records\b"
    r")",
    re.IGNORECASE,
)
_DANGEROUS_PROVIDER_OUTPUT = re.compile(
    r"\b(?:sql|select|insert|update|delete|drop|alter|truncate|write|mutat(?:e|ion)|"
    r"hidden|secret|password|database|execute|jailbreak)\b",
    re.IGNORECASE,
)
_CURRENCY_MARKER = re.compile(r"(?<![\w.])(?:INR|Rs\.?|₹)", re.IGNORECASE)
_CURRENCY_NUMBER = re.compile(r"\s*(-?[\d,]+(?:\.\d+)?)")
_STRICT_PAISE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
_UNSUPPORTED_CURRENCY = re.compile(
    r"(?<![\w.])(?!(?:INR|Rs\.?)(?![\w.]))"
    r"(?:[A-Z]{2,5}|[$€£¥₽₩₺])\s*-?[\d,]+(?:\.\d+)?",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"(?<![\w])-?[\d][\d,]*(?:\.\d+)?(?![\w])")


class CopilotValidationError(ValueError):
    """A scoped request validation failure safe to expose through the API."""

    def __init__(
        self,
        field: str,
        message: str,
        *,
        code: str = "validation_error",
        status_code: int = 422,
    ):
        self.field = field
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class CopilotAnswer(ApiModel):
    answer: str
    mode: InvestigationMode
    citations: list[Citation] = Field(default_factory=list)
    calculation: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


def _as_uuid(value: UUID | str | None, field: str) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise CopilotValidationError(field, f"{field} must be a UUID") from error


def _format_inr(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    whole, paise = divmod(abs(amount), 100)
    return f"INR {sign}{whole:,}.{paise:02d}"


def _parse_inr(value: str) -> int:
    if _STRICT_PAISE.fullmatch(value) is None:
        raise ValueError("INR amounts must use strict paise precision")
    sign = -1 if value.startswith("-") else 1
    unsigned = value.removeprefix("-").replace(",", "")
    whole, _, paise = unsigned.partition(".")
    return sign * (int(whole) * 100 + int((paise + "00")[:2]))


def _provider_currency_amounts(answer: str) -> list[int]:
    if _UNSUPPORTED_CURRENCY.search(answer):
        raise ValueError("Provider answer contains an unsupported currency claim")
    amounts: list[int] = []
    consumed_ranges: list[tuple[int, int]] = []
    for marker in _CURRENCY_MARKER.finditer(answer):
        number = _CURRENCY_NUMBER.match(answer, marker.end())
        if number is None:
            raise ValueError("Provider currency claim is missing an amount")
        raw_value = number.group(1)
        amounts.append(_parse_inr(raw_value))
        consumed_ranges.append((number.start(1), number.end(1)))
        trailing = answer[number.end() :]
        if trailing.startswith((".", ",")) and len(trailing) > 1 and trailing[1].isdigit():
            raise ValueError("Provider currency claim is ambiguous")
        if trailing and trailing[0].isalnum():
            raise ValueError("Provider currency claim is malformed")
    if any(
        not any(start <= number.start() and number.end() <= end for start, end in consumed_ranges)
        for number in _BARE_NUMBER.finditer(answer)
    ):
        raise ValueError("Provider answer contains a bare numeric claim")
    return amounts


def _unsupported_answer(question: str, reason: str) -> CopilotAnswer:
    return CopilotAnswer(
        answer=(
            "Roborecon Copilot only provides read-only, grounded explanations for a "
            "specified settlement. It cannot run SQL, change records, or reveal hidden data."
            if reason == "unsafe"
            else (
                "Roborecon Copilot can explain a specified settlement using persisted "
                "settlement lines."
            )
        ),
        mode=InvestigationMode.deterministic_fallback,
        tool_trace=[
            {
                "tool": "copilot",
                "status": "rejected",
                "error": "unsupported_request",
                "questionLength": len(question),
            }
        ],
        error_code="unsupported_request",
    )


def _is_supported_question(question: str) -> tuple[bool, str]:
    if _DANGEROUS_REQUEST.search(question) or _INJECTION_REQUEST.search(question):
        return False, "unsafe"
    if "settlement" not in question.lower():
        return False, "unsupported"
    return True, ""


def _integer_field(calculation: Mapping[str, Any], name: str) -> int:
    value = calculation.get(name)
    if type(value) is not int:
        raise ValueError(f"Settlement calculation field {name} is not an integer")
    return value


def _validated_breakdown(raw: Any, settlement_id: UUID) -> tuple[dict[str, Any], list[Citation]]:
    if not isinstance(raw, Mapping):
        raise ValueError("Settlement breakdown is not an object")

    calculation = dict(raw)
    captured = _integer_field(calculation, "captured")
    refunds = _integer_field(calculation, "refunds")
    fees = _integer_field(calculation, "fees")
    tax = _integer_field(calculation, "tax")
    held = _integer_field(calculation, "held")
    releases = _integer_field(calculation, "releases")
    adjustments = _integer_field(calculation, "adjustments")
    expected_net = _integer_field(calculation, "expectedNet")
    actual_net = _integer_field(calculation, "actualNet")
    difference = _integer_field(calculation, "difference")
    if captured - refunds - fees - tax - held + releases + adjustments != expected_net:
        raise ValueError("Settlement calculation arithmetic is inconsistent")
    if actual_net - expected_net != difference:
        raise ValueError("Settlement calculation difference is inconsistent")

    settlement_ids = calculation.get("settlementIds")
    line_ids = calculation.get("lineIds")
    bank_credit_ids = calculation.get("bankCreditIds")
    if not all(
        isinstance(value, list)
        for value in (settlement_ids, line_ids, bank_credit_ids)
    ):
        raise ValueError("Settlement breakdown is missing source IDs")
    try:
        parsed_settlement_ids = {UUID(str(item)) for item in settlement_ids}
        parsed_line_ids = {UUID(str(item)) for item in line_ids}
        parsed_bank_credit_ids = {UUID(str(item)) for item in bank_credit_ids}
    except (TypeError, ValueError) as error:
        raise ValueError("Settlement breakdown contains invalid source IDs") from error
    if parsed_settlement_ids != {settlement_id}:
        raise ValueError("Settlement breakdown returned an unexpected settlement")

    try:
        citations = [Citation.model_validate(item) for item in calculation["citations"]]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Settlement breakdown citations are invalid") from error
    citation_pairs = {(item.source_type, item.source_id) for item in citations}
    expected_pairs = {("settlement", settlement_id)} | {
        ("settlement_line", line_id) for line_id in parsed_line_ids
    } | {
        ("bank_credit", bank_credit_id) for bank_credit_id in parsed_bank_credit_ids
    }
    if citation_pairs != expected_pairs or len(citations) != len(citation_pairs):
        raise ValueError("Settlement breakdown citations are not exact")
    calculation["gst"] = tax
    return calculation, citations


def _deterministic_answer(calculation: Mapping[str, Any]) -> str:
    expected_net = _integer_field(calculation, "expectedNet")
    actual_net = _integer_field(calculation, "actualNet")
    difference = _integer_field(calculation, "difference")
    return (
        f"Captured payments total {_format_inr(_integer_field(calculation, 'captured'))}. "
        f"Refunds reduce this by {_format_inr(_integer_field(calculation, 'refunds'))}; "
        f"fees reduce it by {_format_inr(_integer_field(calculation, 'fees'))}; "
        f"GST/tax reduces it by {_format_inr(_integer_field(calculation, 'tax'))}; "
        f"held amounts reduce it by {_format_inr(_integer_field(calculation, 'held'))}; "
        f"releases add {_format_inr(_integer_field(calculation, 'releases'))} and "
        f"adjustments add {_format_inr(_integer_field(calculation, 'adjustments'))}. "
        f"The expected settlement net is {_format_inr(expected_net)}. "
        f"The persisted settlement amount is {_format_inr(actual_net)}, "
        f"a difference of {_format_inr(difference)}."
    )


def _fallback(
    calculation: dict[str, Any] | None,
    citations: list[Citation],
    trace: list[dict[str, Any]],
    *,
    error_code: str | None,
) -> CopilotAnswer:
    if calculation is None:
        return CopilotAnswer(
            answer="A grounded settlement breakdown was not available for this request.",
            mode=InvestigationMode.deterministic_fallback,
            citations=citations,
            calculation=None,
            tool_trace=trace,
            error_code=error_code,
        )
    return CopilotAnswer(
        answer=_deterministic_answer(calculation),
        mode=InvestigationMode.deterministic_fallback,
        citations=citations,
        calculation=calculation,
        tool_trace=trace,
        error_code=error_code,
    )


def _provider_error_code(error: BaseException) -> str:
    if isinstance(error, ProviderError):
        return error.code
    if isinstance(error, ToolError):
        return "tool_error"
    return "provider_error"


def _provider_context(
    settlement_id: UUID,
    batch_id: UUID,
    run_id: UUID,
    question: str,
    calculation: dict[str, Any],
    citations: list[Citation],
) -> InvestigationContext:
    return InvestigationContext(
        exception_id=settlement_id,
        batch_id=batch_id,
        run_id=run_id,
        exception_type="settlement_explanation",
        exception_message=question,
        amount=calculation["actualNet"],
        deterministic_status="settlement_explanation",
        deterministic_evidence=[calculation],
        allowed_source_ids=[item.source_id for item in citations],
        source_references=citations,
        tool_results=[
            ToolResult(
                tool="get_settlement_breakdown",
                data=calculation,
                citations=citations,
            )
        ],
    )


def _normalise_provider_recommendation(raw: Any) -> ProviderRecommendation:
    if isinstance(raw, ProviderRecommendation):
        return raw
    if isinstance(raw, Mapping):
        return ProviderRecommendation.model_validate(raw)
    raise ValueError("Provider response is not a recommendation")


def _validate_provider_answer(
    recommendation: ProviderRecommendation,
    calculation: Mapping[str, Any],
    citations: list[Citation],
) -> None:
    if recommendation.tool_request is not None:
        raise ValueError("Provider requested an unapproved tool")
    valid_pairs = {(item.source_type, item.source_id) for item in citations}
    if not recommendation.citations or any(
        (item.source_type, item.source_id) not in valid_pairs
        for item in recommendation.citations
    ):
        raise ValueError("Provider returned an invalid citation")
    answer = recommendation.recommendation.strip()
    if (
        not answer
        or _DANGEROUS_PROVIDER_OUTPUT.search(answer)
        or _INJECTION_REQUEST.search(answer)
    ):
        raise ValueError("Provider answer is not a safe paraphrase")
    allowed_amounts = {
        _integer_field(calculation, name)
        for name in (
            "captured",
            "refunds",
            "fees",
            "tax",
            "held",
            "releases",
            "adjustments",
            "expectedNet",
            "actualNet",
            "difference",
        )
    }
    provider_amounts = _provider_currency_amounts(answer)
    if _integer_field(calculation, "expectedNet") not in provider_amounts:
        raise ValueError("Provider answer does not contain the validated settlement net")
    if any(amount not in allowed_amounts for amount in provider_amounts):
        raise ValueError("Provider answer contains an ungrounded amount")


async def _release_read_transaction(session: AsyncSession) -> bool:
    if not await _transaction_is_active(session):
        return True
    try:
        await session.rollback()
    except Exception:
        return False
    return True


async def _transaction_is_active(session: AsyncSession) -> bool:
    in_transaction = getattr(session, "in_transaction", None)
    if not callable(in_transaction):
        return False
    transaction = in_transaction()
    if isawaitable(transaction):
        transaction = await transaction
    return bool(transaction)


async def _provider_answer(
    question: str,
    settlement_id: UUID,
    batch_id: UUID,
    run_id: UUID,
    calculation: dict[str, Any],
    citations: list[Citation],
    trace: list[dict[str, Any]],
) -> tuple[str, str] | None:
    context = _provider_context(
        settlement_id,
        batch_id,
        run_id,
        question,
        calculation,
        citations,
    )
    providers = configured_providers()
    last_error = "provider_unavailable" if not providers else "provider_error"
    for provider in providers:
        provider_name = str(getattr(provider, "name", "provider"))[:100]
        provider_model = str(getattr(provider, "model", "unknown"))[:150]
        try:
            recommendation = _normalise_provider_recommendation(
                await provider.investigate(context)
            )
            if recommendation.tool_request is not None:
                trace.append(
                    {
                        "tool": recommendation.tool_request.tool[:100],
                        "provider": provider_name,
                        "model": provider_model,
                        "status": "rejected",
                        "reason": "provider_tool_request",
                    }
                )
                last_error = "provider_tool_request"
                continue
            _validate_provider_answer(recommendation, calculation, citations)
        except Exception as error:
            last_error = (
                "invalid_citation"
                if "citation" in str(error).lower()
                else "invalid_answer"
                if isinstance(error, ValueError)
                else _provider_error_code(error)
            )
            trace.append(
                {
                    "provider": provider_name,
                    "model": provider_model,
                    "status": "failed",
                    "error": last_error,
                }
            )
            continue
        trace.append(
            {
                "provider": provider_name,
                "model": provider_model,
                "status": "recommendation",
            }
        )
        return recommendation.recommendation.strip(), provider_name
    trace.append({"status": "provider_fallback", "error": last_error})
    return None


async def answer_question(
    session: AsyncSession,
    question: str,
    run_id: UUID | str | None = None,
    settlement_id: UUID | str | None = None,
) -> CopilotAnswer:
    if not isinstance(question, str) or not question.strip() or len(question) > 2_000:
        raise CopilotValidationError(
            "question",
            "question must contain between 1 and 2000 characters",
        )
    clean_question = question.strip()
    supported, reason = _is_supported_question(clean_question)
    if not supported:
        return _unsupported_answer(clean_question, reason)

    requested_settlement_id = _as_uuid(settlement_id, "settlement_id")
    if requested_settlement_id is None:
        raise CopilotValidationError(
            "settlement_id",
            "settlement_id is required for a grounded settlement explanation",
        )
    requested_run_id = _as_uuid(run_id, "run_id")
    caller_transaction_active = await _transaction_is_active(session)
    run = None
    if requested_run_id is not None:
        run = await session.get(ReconciliationRun, requested_run_id)
        if run is None:
            raise CopilotValidationError(
                "run_id",
                "run_id: Reconciliation run was not found",
                code="run_not_found",
                status_code=404,
            )

    settlement = await session.get(Settlement, requested_settlement_id)
    if settlement is None:
        raise CopilotValidationError(
            "settlement_id",
            "settlement_id: Settlement was not found",
            code="settlement_not_found",
            status_code=404,
        )
    batch_id = settlement.batch_id
    if run is not None and batch_id != run.batch_id:
        raise CopilotValidationError(
            "settlement_id",
            "settlement_id: Settlement is outside the requested reconciliation run",
            code="settlement_outside_run",
        )
    context = InvestigationContext(
        exception_id=requested_settlement_id,
        batch_id=batch_id,
        run_id=requested_run_id,
        exception_type="settlement_explanation",
        allowed_source_ids=[requested_settlement_id],
    )
    trace = [
        {
            "tool": "get_settlement_breakdown",
            "sourceIds": [str(requested_settlement_id)],
            "status": "completed",
        }
    ]
    breakdown_error: str | None = None
    try:
        raw_breakdown = await ToolExecutor(session, context).execute(
            "get_settlement_breakdown",
            {"source_ids": [str(requested_settlement_id)]},
        )
        calculation, citations = _validated_breakdown(
            raw_breakdown, requested_settlement_id
        )
    except ToolError:
        breakdown_error = "tool_error"
    except ValueError:
        breakdown_error = "invalid_breakdown"

    if breakdown_error is not None:
        if not caller_transaction_active and not await _release_read_transaction(session):
            trace[0]["status"] = "rejected"
            trace[0]["error"] = "transaction_release_failed"
            return _fallback(
                None,
                [],
                trace,
                error_code="transaction_release_failed",
            )
        trace[0]["status"] = "rejected"
        trace[0]["error"] = breakdown_error
        return _fallback(None, [], trace, error_code=breakdown_error)

    if caller_transaction_active:
        trace.append(
            {
                "status": "provider_skipped",
                "reason": "caller_transaction_active",
            }
        )
        return _fallback(
            calculation,
            citations,
            trace,
            error_code="provider_scope_unavailable",
        )

    if not await _release_read_transaction(session):
        trace[0]["status"] = "rejected"
        trace[0]["error"] = "transaction_release_failed"
        return _fallback(
            None,
            [],
            trace,
            error_code="transaction_release_failed",
        )
    if run is None:
        trace.append({"status": "provider_skipped", "reason": "run_required"})
        return _fallback(
            calculation,
            citations,
            trace,
            error_code="provider_scope_unavailable",
        )

    provider_result = await _provider_answer(
        clean_question,
        requested_settlement_id,
        batch_id,
        requested_run_id,
        calculation,
        citations,
        trace,
    )
    if provider_result is None:
        return _fallback(
            calculation,
            citations,
            trace,
            error_code=trace[-1].get("error", "provider_unavailable"),
        )
    answer, _provider_name = provider_result
    return CopilotAnswer(
        answer=answer,
        mode=InvestigationMode.provider,
        citations=citations,
        calculation=calculation,
        tool_trace=trace,
    )
