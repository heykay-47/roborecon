from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model import (
    MAX_SOURCE_IDS_PER_CALL,
    InvestigationContext,
)
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.reconciliation.model import (
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine


class ToolError(RuntimeError):
    pass


class UnknownToolError(ToolError):
    pass


class ToolInputError(ToolError):
    pass


class CrossBatchSourceError(ToolInputError):
    pass


_SOURCE_MODELS = (
    ("ledger", LedgerEntry),
    ("razorpay_order", RazorpayOrder),
    ("razorpay_payment", RazorpayPayment),
    ("razorpay_refund", RazorpayRefund),
    ("settlement", Settlement),
    ("settlement_line", SettlementLine),
    ("bank_credit", BankCredit),
)

_SOURCE_FIELDS = {
    "ledger": ("id", "reference", "entry_type", "amount", "currency", "business_at"),
    "razorpay_order": (
        "id",
        "provider_order_id",
        "receipt",
        "amount",
        "currency",
        "status",
        "business_at",
    ),
    "razorpay_payment": (
        "id",
        "provider_payment_id",
        "provider_order_id",
        "receipt",
        "amount",
        "currency",
        "status",
        "captured",
        "business_at",
    ),
    "razorpay_refund": (
        "id",
        "provider_refund_id",
        "provider_payment_id",
        "amount",
        "currency",
        "status",
        "business_at",
    ),
    "settlement": (
        "id",
        "provider_settlement_id",
        "amount",
        "fee",
        "tax",
        "held_amount",
        "currency",
        "utr",
        "status",
        "business_at",
    ),
    "settlement_line": (
        "id",
        "settlement_id",
        "line_type",
        "reference",
        "amount",
        "currency",
        "business_at",
    ),
    "bank_credit": ("id", "settlement_id", "utr", "amount", "currency"),
}

GEMINI_TOOL_DECLARATIONS = [
    {
        "name": "get_run_metrics",
        "description": "Read operational metrics for the current reconciliation run.",
        "parameters": {"type": "OBJECT", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_exception_evidence",
        "description": "Read deterministic evidence for the current exception.",
        "parameters": {"type": "OBJECT", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_settlement_breakdown",
        "description": "Read integer-paise settlement arithmetic for cited settlement IDs.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["source_ids"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_source_records",
        "description": "Read capped source records from the current batch only.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["source_ids"],
            "additionalProperties": False,
        },
    },
]

def _openai_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: item.lower() if key == "type" and isinstance(item, str) else _openai_schema(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_openai_schema(item) for item in value]
    return value


GROQ_TOOL_DECLARATIONS = [
    {
        "type": "function",
        "function": {
            "name": item["name"],
            "description": item["description"],
            "parameters": _openai_schema(item["parameters"]),
            "strict": True,
        },
    }
    for item in GEMINI_TOOL_DECLARATIONS
]


def _value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _source_record(source_type: str, row: Any) -> dict[str, Any]:
    return {
        field: _value(getattr(row, field))
        for field in _SOURCE_FIELDS[source_type]
        if hasattr(row, field)
    }


def _ids(arguments: Mapping[str, Any], *, required: bool = True) -> list[UUID]:
    value = arguments.get(
        "source_ids",
        arguments.get(
            "sourceIds",
            arguments.get("settlement_ids", arguments.get("settlementIds")),
        ),
    )
    if value is None and not required:
        return []
    if not isinstance(value, list) or len(value) > MAX_SOURCE_IDS_PER_CALL:
        raise ToolInputError(
            f"source_ids must contain at most {MAX_SOURCE_IDS_PER_CALL} IDs"
        )
    try:
        return [UUID(str(item)) for item in value]
    except (ValueError, TypeError) as error:
        raise ToolInputError("source_ids must contain UUIDs") from error


class ToolExecutor:
    """Application-owned read-only tool boundary for one exception context."""

    def __init__(self, session: AsyncSession, context: InvestigationContext):
        self.session = session
        self.context = context

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        context: InvestigationContext | None = None,
    ) -> dict[str, Any]:
        active_context = context or self.context
        handlers = {
            "get_run_metrics": self.get_run_metrics,
            "get_exception_evidence": self.get_exception_evidence,
            "get_settlement_breakdown": self.get_settlement_breakdown,
            "get_source_records": self.get_source_records,
        }
        handler = handlers.get(name)
        if handler is None:
            raise UnknownToolError(f"Tool is not allowed: {name}")
        self.context = active_context
        return await handler(arguments or {})

    async def get_run_metrics(
        self, _arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        run = await self.session.get(ReconciliationRun, self.context.run_id)
        if run is None or run.batch_id != self.context.batch_id:
            raise ToolInputError("Run is outside the investigation batch")
        metrics = run.metrics or {}
        safe_metrics = {
            key: metrics[key]
            for key in (
                "recordsProcessed",
                "durationMs",
                "throughput",
                "sourceThroughput",
                "settlementNet",
            )
            if key in metrics
        }
        return {
            "runId": str(run.id),
            "batchId": str(run.batch_id),
            "status": _value(run.status),
            "sourceRowCount": run.source_row_count,
            "sourceCounts": run.source_counts or {},
            "durationMs": run.duration_ms,
            "throughput": run.throughput,
            "metrics": safe_metrics,
        }

    async def get_exception_evidence(
        self, _arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        exception = await self.session.get(ReconciliationException, self.context.exception_id)
        if exception is None or exception.batch_id != self.context.batch_id:
            raise ToolInputError("Exception is outside the investigation batch")
        result = None
        if exception.result_id is not None:
            result = await self.session.get(ReconciliationResult, exception.result_id)
        return {
            "exceptionId": str(exception.id),
            "exceptionType": exception.exception_type,
            "status": _value(exception.status),
            "amount": exception.amount,
            "message": exception.message,
            "result": (
                {
                    "status": _value(result.status),
                    "stage": _value(result.stage),
                    "score": result.score,
                    "runnerUpScore": result.runner_up_score,
                    "margin": result.margin,
                    "selectedIds": [str(item) for item in result.selected_ids],
                    "evidence": result.evidence,
                    "candidates": result.candidates,
                }
                if result is not None
                else None
            ),
        }

    async def get_source_records(
        self, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments = arguments or {}
        source_ids = _ids(arguments)
        allowed = set(self.context.allowed_source_ids)
        outside_batch = [source_id for source_id in source_ids if source_id not in allowed]
        if outside_batch:
            raise CrossBatchSourceError("Source ID is not part of the current batch")
        records: list[dict[str, Any]] = []
        for source_id in source_ids:
            found = False
            for source_type, model in _SOURCE_MODELS:
                result = await self.session.execute(
                    select(model).where(
                        model.id == source_id,
                        model.batch_id == self.context.batch_id,
                    )
                )
                row = result.scalars().first() if hasattr(result.scalars(), "first") else None
                if row is None:
                    rows = result.scalars().all()
                    row = rows[0] if rows else None
                if row is not None:
                    records.append({"sourceType": source_type, **_source_record(source_type, row)})
                    found = True
                    break
            if not found:
                raise ToolInputError("Source record was not found in the current batch")
        return {
            "records": records,
            "citations": [
                {"source_type": item["sourceType"], "source_id": item["id"]}
                for item in records
            ],
        }

    async def get_settlement_breakdown(
        self, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments = arguments or {}
        settlement_ids = _ids(arguments)
        allowed = set(self.context.allowed_source_ids)
        if any(source_id not in allowed for source_id in settlement_ids):
            raise CrossBatchSourceError("Settlement ID is not part of the current batch")
        settlements = await self._rows(
            Settlement,
            Settlement.id.in_(settlement_ids),
        )
        if not settlements:
            raise ToolInputError("Settlement records were not found in the current batch")
        settlement_id_set = {row.id for row in settlements}
        lines = await self._rows(
            SettlementLine,
            SettlementLine.settlement_id.in_(settlement_id_set),
        )
        credits = await self._rows(
            BankCredit,
            BankCredit.settlement_id.in_(settlement_id_set),
        )

        captured = sum(row.amount for row in lines if _value(row.line_type) == "payment")
        refunds = sum(row.amount for row in lines if _value(row.line_type) == "refund")
        fees = sum(row.amount for row in lines if _value(row.line_type) == "fee")
        tax = sum(row.amount for row in lines if _value(row.line_type) == "tax")
        held = sum(row.amount for row in lines if _value(row.line_type) == "hold")
        releases = sum(row.amount for row in lines if _value(row.line_type) == "release")
        adjustments = sum(
            row.amount for row in lines if _value(row.line_type) == "adjustment"
        )
        expected_net = captured - refunds - fees - tax - held + releases + adjustments
        actual_net = sum(row.amount for row in settlements)
        return {
            "settlementIds": [str(row.id) for row in settlements],
            "captured": captured,
            "refunds": refunds,
            "fees": fees,
            "tax": tax,
            "held": held,
            "releases": releases,
            "adjustments": adjustments,
            "expectedNet": expected_net,
            "actualNet": actual_net,
            "difference": actual_net - expected_net,
            "lineIds": [str(row.id) for row in lines],
            "bankCreditIds": [str(row.id) for row in credits],
            "citations": [
                {"source_type": "settlement", "source_id": str(row.id)}
                for row in settlements
            ]
            + [
                {"source_type": "settlement_line", "source_id": str(row.id)}
                for row in lines
            ]
            + [
                {"source_type": "bank_credit", "source_id": str(row.id)}
                for row in credits
            ],
        }

    async def _rows(self, model: Any, condition: Any) -> list[Any]:
        result = await self.session.execute(
            select(model).where(model.batch_id == self.context.batch_id, condition)
        )
        return list(result.scalars().all())
