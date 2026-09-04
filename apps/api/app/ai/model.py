from __future__ import annotations

import enum
import json
import uuid
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base import Base


class InvestigationMode(str, enum.Enum):
    provider = "provider"
    deterministic_fallback = "deterministicFallback"


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=50)
    source_id: uuid.UUID


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = Field(default=None, max_length=100)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    data: Any
    citations: list[Citation] = Field(default_factory=list)


class InvestigationContext(BaseModel):
    """Provider-visible investigation state with no database capability."""

    model_config = ConfigDict(extra="forbid")

    exception_id: uuid.UUID
    batch_id: uuid.UUID
    run_id: uuid.UUID | None = None
    exception_type: str
    exception_message: str = ""
    amount: int | None = None
    deterministic_status: str | None = None
    deterministic_evidence: list[dict[str, Any]] = Field(default_factory=list)
    allowed_source_ids: list[uuid.UUID] = Field(default_factory=list)
    source_references: list[Citation] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    def prompt(self) -> str:
        return (
            "Investigate this reconciliation exception using only read-only tools. "
            "The deterministic reconciliation outcome remains authoritative. "
            "Do not request SQL, mutations, hidden truth, or records outside this batch.\n"
            "Use native function calling when more evidence is needed. Call "
            "get_exception_evidence first, and pass only internal UUID source IDs returned "
            "by evidence or tool citations to source lookup tools; never pass provider IDs. "
            "After using tools, "
            "return one raw JSON object without Markdown fences: recommendation must be a "
            "string, confidence must be an integer from 0 to 100, citations must contain "
            "source_type and source_id copied from evidence or tool results, and "
            "tool_request must be null. Include at least one valid citation.\n"
            f"Exception type: {self.exception_type}\n"
            f"Exception message: {self.exception_message}\n"
            f"Amount in INR paise: {self.amount}\n"
            f"Deterministic status: {self.deterministic_status}\n"
            f"Evidence: {self.deterministic_evidence}"
        )


class ProviderRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: str = Field(default="", max_length=4000)
    confidence: int = Field(default=0, ge=0, le=100)
    citations: list[Citation] = Field(default_factory=list)
    tool_request: ToolRequest | None = None


class BatchCloseCitation(BaseModel):
    """A provider citation that must point at a run exception or its source evidence."""

    model_config = ConfigDict(extra="forbid")

    exception_id: uuid.UUID = Field(
        validation_alias=AliasChoices("exception_id", "exceptionId"),
        serialization_alias="exceptionId",
    )
    source_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_type", "sourceType"),
        serialization_alias="sourceType",
    )
    source_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("source_id", "sourceId"),
        serialization_alias="sourceId",
    )


class BatchCloseExceptionContext(BaseModel):
    """Compact, source-visible exception data safe to send to a provider."""

    model_config = ConfigDict(extra="forbid")

    exception_id: uuid.UUID = Field(
        validation_alias=AliasChoices("exception_id", "exceptionId"),
        serialization_alias="exceptionId",
    )
    exception_type: str = Field(
        validation_alias=AliasChoices("exception_type", "exceptionType"),
        serialization_alias="exceptionType",
    )
    stage: str | None = None
    status: str
    amount: int = 0
    message: str = Field(max_length=4000)
    rule_codes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("rule_codes", "ruleCodes"),
        serialization_alias="ruleCodes",
    )
    contradiction_codes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("contradiction_codes", "contradictionCodes"),
        serialization_alias="contradictionCodes",
    )
    citations: list[BatchCloseCitation] = Field(default_factory=list)


class BatchCloseContext(BaseModel):
    """Truth-free run digest used for one bounded Batch Close provider call."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID = Field(
        validation_alias=AliasChoices("run_id", "runId"),
        serialization_alias="runId",
    )
    batch_id: uuid.UUID = Field(
        validation_alias=AliasChoices("batch_id", "batchId"),
        serialization_alias="batchId",
    )
    source_row_count: int = Field(
        validation_alias=AliasChoices("source_row_count", "sourceRows"),
        serialization_alias="sourceRows",
    )
    result_count: int = Field(
        validation_alias=AliasChoices("result_count", "results"),
        serialization_alias="results",
    )
    money_reconciled: int = Field(
        validation_alias=AliasChoices("money_reconciled", "moneyReconciled"),
        serialization_alias="moneyReconciled",
    )
    money_unresolved: int = Field(
        validation_alias=AliasChoices("money_unresolved", "moneyUnresolved"),
        serialization_alias="moneyUnresolved",
    )
    operational_metrics: dict[str, Any] = Field(
        validation_alias=AliasChoices("operational_metrics", "operationalMetrics"),
        serialization_alias="operationalMetrics",
    )
    source_counts: dict[str, int] = Field(
        validation_alias=AliasChoices("source_counts", "sourceCounts"),
        serialization_alias="sourceCounts",
    )
    result_summaries: list[dict[str, Any]] = Field(
        validation_alias=AliasChoices("result_summaries", "resultSummaries"),
        serialization_alias="resultSummaries",
    )
    open_exceptions: list[BatchCloseExceptionContext] = Field(
        validation_alias=AliasChoices("open_exceptions", "openExceptions"),
        serialization_alias="openExceptions",
    )

    def prompt(self) -> str:
        digest = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            "Assess this completed reconciliation run using only the supplied digest. "
            "Deterministic coverage and money totals are authoritative. Do not request "
            "tools, SQL, mutations, hidden truth, or records outside this run. Return one "
            "raw JSON object with a themes array. Each theme must contain title, summary, "
            "exceptionIds, reviewAction, and citations. Assign every open exception exactly "
            "once. Each citation must copy an exceptionId from the supplied open exceptions. "
            "Do not return benchmark accuracy or evaluation claims.\n"
            f"Run digest: {digest}"
        )


class BatchCloseProviderTheme(BaseModel):
    """Strict provider-suggested cross-exception theme."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=200,
    )
    summary: str = Field(
        min_length=1,
        max_length=2000,
    )
    exception_ids: list[uuid.UUID] = Field(
        min_length=1,
        validation_alias=AliasChoices("exception_ids", "exceptionIds"),
        serialization_alias="exceptionIds",
    )
    review_action: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("review_action", "reviewAction"),
        serialization_alias="reviewAction",
    )
    citations: list[BatchCloseCitation] = Field(min_length=1)


class BatchCloseProviderResponse(BaseModel):
    """Complete typed response expected from one Batch Close provider call."""

    model_config = ConfigDict(extra="forbid")

    themes: list[BatchCloseProviderTheme] = Field(min_length=1)


class AIInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: uuid.UUID | None = None
    exception_id: uuid.UUID
    run_id: uuid.UUID
    batch_id: uuid.UUID
    mode: InvestigationMode
    provider: str | None = None
    model: str | None = None
    recommendation: str
    confidence: int = Field(ge=0, le=100)
    citations: list[Citation] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class AIInvestigationRecord(Base):
    """Persisted advisory output; it cannot alter deterministic outcomes."""

    __tablename__ = "ai_investigations"

    exception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_exceptions.id"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    tool_trace: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
