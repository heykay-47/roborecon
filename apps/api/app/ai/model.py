from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
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
