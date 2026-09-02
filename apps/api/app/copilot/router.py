from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.model import Citation
from app.common.api import ApiModel
from app.copilot.service import CopilotAnswer, CopilotValidationError, answer_question
from app.database import get_session

router = APIRouter(prefix="/copilot", tags=["copilot"])


class CopilotAskRequest(ApiModel):
    question: str = Field(min_length=1, max_length=2_000)
    run_id: UUID | None = None
    settlement_id: UUID | None = None


class CopilotCitation(ApiModel):
    source_type: str
    source_id: UUID


class CopilotResponse(ApiModel):
    answer: str
    mode: str
    citations: list[CopilotCitation]
    calculation: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    error_code: str | None = None


def _citation_response(citation: Citation) -> CopilotCitation:
    return CopilotCitation(
        source_type=citation.source_type,
        source_id=citation.source_id,
    )


def _response(answer: CopilotAnswer) -> CopilotResponse:
    return CopilotResponse(
        answer=answer.answer,
        mode=answer.mode.value,
        citations=[_citation_response(item) for item in answer.citations],
        calculation=answer.calculation,
        tool_trace=answer.tool_trace,
        error_code=answer.error_code,
    )


@router.post("/ask", response_model=CopilotResponse)
async def ask_copilot(
    request: CopilotAskRequest,
    session: AsyncSession = Depends(get_session),
) -> CopilotResponse:
    try:
        answer = await answer_question(
            session,
            request.question,
            run_id=request.run_id,
            settlement_id=request.settlement_id,
        )
    except CopilotValidationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "field": error.field, "message": str(error)},
        ) from error
    return _response(answer)
