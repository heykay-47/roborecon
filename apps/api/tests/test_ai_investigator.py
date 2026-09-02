from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from app.ai import investigator as investigator_module
from app.ai.investigator import (
    investigate_completed_run,
    investigate_exception,
    select_exception_portfolio,
)
from app.ai.model import (
    Citation,
    InvestigationContext,
    ProviderRecommendation,
    ToolRequest,
)
from app.ai.provider import GeminiProvider, ProviderError
from app.ai.tools import CrossBatchSourceError, ToolExecutor
from app.common.enums import ExceptionStatus, RunStatus

EXCEPTION_ID = UUID("c3ff0d98-5ed8-5e1a-bf69-5a43a90dcbbb")
BATCH_ID = UUID("4c4f7f9d-82de-4673-8a5d-a8dbf9e61a11")
RUN_ID = UUID("d5c84fc4-6f42-4b55-8e0f-77e4ccf92c7d")
SOURCE_ID = UUID("f6ef4e1a-e8be-44cc-a3ad-a9bf7aa6fdb1")


class _Result:
    def __init__(self, rows=None, scalar_value=0):
        self.rows = list(rows or [])
        self.scalar_value = scalar_value

    def scalar(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, exception, run, result):
        self.rows = {
            "exception": exception,
            "run": run,
            "result": result,
        }
        self.added = []
        self.execute_calls = 0
        self.commits = 0

    async def get(self, model, row_id):
        name = model.__name__
        if name == "ReconciliationException":
            return self.rows["exception"] if row_id == EXCEPTION_ID else None
        if name == "ReconciliationRun":
            return self.rows["run"] if row_id == RUN_ID else None
        if name == "ReconciliationResult":
            return self.rows["result"] if row_id == self.rows["exception"].result_id else None
        return None

    async def execute(self, statement):
        self.execute_calls += 1
        return _Result()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


def _session():
    result = SimpleNamespace(
        id=uuid4(),
        batch_id=BATCH_ID,
        run_id=RUN_ID,
        primary_source_type="ledger",
        primary_source_id=SOURCE_ID,
        amount=125_00,
        currency="INR",
        status=SimpleNamespace(value="ambiguous"),
        score=78,
        runner_up_score=62,
        margin=16,
        evidence=[{"rule_code": "reference_similarity", "points": 78}],
        candidates=[{"candidate_id": str(SOURCE_ID), "score": 78}],
        selected_ids=[str(SOURCE_ID)],
    )
    exception = SimpleNamespace(
        id=EXCEPTION_ID,
        result_id=result.id,
        run_id=RUN_ID,
        batch_id=BATCH_ID,
        status=ExceptionStatus.open,
        exception_type="ambiguous",
        source_type="ledger",
        source_id=SOURCE_ID,
        amount=125_00,
        message="Deterministic outcome requires review",
    )
    run = SimpleNamespace(
        id=RUN_ID,
        batch_id=BATCH_ID,
        status=RunStatus.completed,
        source_counts={"total": 1},
        source_row_count=1,
        duration_ms=4,
        throughput=250.0,
        metrics={"precision": 100.0, "recordsProcessed": 1},
    )
    return _Session(exception, run, result), exception, run, result


class _FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, response=None, responses=None):
        self.response = response
        self.responses = list(responses or [])
        self.contexts = []

    async def investigate(self, context: InvestigationContext):
        self.contexts.append(context)
        if self.responses:
            return self.responses.pop(0)
        return self.response


class _FakeTools:
    def __init__(self):
        self.executed_tools = []

    async def execute(self, name, arguments, context):
        self.executed_tools.append(name)
        return {"tool": name, "sourceIds": [str(SOURCE_ID)]}


@pytest.mark.asyncio
async def test_model_cannot_request_unknown_tool():
    session, exception, _, _ = _session()
    provider = _FakeProvider({"tool": "execute_sql", "arguments": {"sql": "DELETE"}})
    tools = _FakeTools()

    result = await investigate_exception(session, exception.id, provider=provider, tools=tools)

    assert result.mode == "deterministicFallback"
    assert "execute_sql" not in tools.executed_tools
    assert exception.status is ExceptionStatus.open
    assert result.error_code == "unknown_tool"


@pytest.mark.asyncio
async def test_provider_failure_returns_deterministic_fallback_without_mutating_exception():
    session, exception, _, _ = _session()
    provider = _FakeProvider()

    async def fail(_context):
        raise TimeoutError("provider timed out")

    provider.investigate = fail
    result = await investigate_exception(session, exception.id, provider=provider)

    assert result.mode == "deterministicFallback"
    assert result.error_code == "timeout"
    assert result.citations[0].source_id == SOURCE_ID
    assert exception.status is ExceptionStatus.open


@pytest.mark.asyncio
async def test_tool_rounds_are_capped_at_four():
    session, exception, _, _ = _session()
    provider = _FakeProvider(
        responses=[
            {"tool": "get_exception_evidence", "arguments": {}}
            for _ in range(8)
        ]
    )
    tools = _FakeTools()

    result = await investigate_exception(session, exception.id, provider=provider, tools=tools)

    assert result.mode == "deterministicFallback"
    assert result.error_code == "tool_round_limit"
    assert len(tools.executed_tools) == 4
    assert len(provider.contexts) == 4
    assert len([item for item in result.tool_trace if "tool" in item]) == 4


@pytest.mark.asyncio
async def test_provider_order_is_gemini_then_groq_then_fallback(monkeypatch):
    session, exception, _, _ = _session()
    gemini = _FakeProvider()
    gemini.name = "gemini"
    gemini.model = "gemini-test"
    groq = _FakeProvider(
        ProviderRecommendation(
            recommendation="Use the cited deterministic evidence.",
            citations=[Citation(source_type="ledger", source_id=SOURCE_ID)],
        )
    )
    groq.name = "groq"
    groq.model = "groq-test"

    async def fail(_context):
        raise ProviderError("gemini", "gemini-test", "rate_limited")

    gemini.investigate = fail
    monkeypatch.setattr(
        investigator_module,
        "configured_providers",
        lambda: [gemini, groq],
    )

    result = await investigate_exception(session, exception.id)

    assert result.mode == "provider"
    assert result.provider == "groq"
    assert result.tool_trace[0]["provider"] == "gemini"
    assert result.tool_trace[0]["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_source_id_cap_rejects_before_tool_execution():
    session, exception, _, _ = _session()
    provider = _FakeProvider(
        {
            "tool": "get_source_records",
            "arguments": {"source_ids": [str(uuid4()) for _ in range(11)]},
        }
    )
    tools = _FakeTools()

    result = await investigate_exception(session, exception.id, provider=provider, tools=tools)

    assert result.mode == "deterministicFallback"
    assert result.error_code == "source_id_limit"
    assert tools.executed_tools == []


@pytest.mark.asyncio
async def test_valid_provider_recommendation_preserves_citations():
    session, exception, _, _ = _session()
    provider = _FakeProvider(
        ProviderRecommendation(
            recommendation="Review the fuzzy reference against the ledger source.",
            confidence=81,
            citations=[Citation(source_type="ledger", source_id=SOURCE_ID)],
        )
    )

    result = await investigate_exception(session, exception.id, provider=provider)

    assert result.mode == "provider"
    assert result.recommendation.startswith("Review")
    assert result.citations == [Citation(source_type="ledger", source_id=SOURCE_ID)]
    assert result.provider == "fake"


@pytest.mark.asyncio
async def test_invalid_provider_citation_falls_back():
    session, exception, _, _ = _session()
    provider = _FakeProvider(
        ProviderRecommendation(
            recommendation="Use an unrelated record.",
            citations=[Citation(source_type="ledger", source_id=uuid4())],
        )
    )

    result = await investigate_exception(session, exception.id, provider=provider)

    assert result.mode == "deterministicFallback"
    assert result.error_code == "invalid_citation"


@pytest.mark.asyncio
async def test_provider_context_contains_no_database_or_mutation_capability():
    session, exception, _, _ = _session()
    provider = _FakeProvider(
        ProviderRecommendation(recommendation="Evidence is internally consistent.")
    )

    await investigate_exception(session, exception.id, provider=provider)

    context = provider.contexts[0]
    assert not hasattr(context, "session")
    assert not hasattr(context, "execute_sql")
    assert not hasattr(context, "mutate")


@pytest.mark.asyncio
async def test_cross_batch_source_id_is_rejected():
    foreign_id = uuid4()
    context = InvestigationContext(
        exception_id=EXCEPTION_ID,
        batch_id=BATCH_ID,
        run_id=RUN_ID,
        exception_type="duplicate",
        allowed_source_ids=[SOURCE_ID],
    )
    executor = ToolExecutor(_Session(*_session()[1:]), context)

    with pytest.raises(CrossBatchSourceError):
        await executor.get_source_records({"source_ids": [str(foreign_id)]})


def test_selector_returns_one_highest_value_exception_per_risk_class():
    rows = [
        SimpleNamespace(id=uuid4(), exception_type="ambiguous", amount=2_000),
        SimpleNamespace(id=uuid4(), exception_type="fuzzy_reference", amount=9_000),
        SimpleNamespace(id=uuid4(), exception_type="duplicate", amount=8_000),
        SimpleNamespace(id=uuid4(), exception_type="duplicate", amount=4_000),
        SimpleNamespace(id=uuid4(), exception_type="refund", amount=7_000),
        SimpleNamespace(id=uuid4(), exception_type="held_released_settlement", amount=6_000),
        SimpleNamespace(id=uuid4(), exception_type="amount_mismatch", amount=5_000),
    ]

    selected = select_exception_portfolio(rows)

    assert len(selected) == 5
    assert {row.exception_type for row in selected} == {
        "fuzzy_reference",
        "duplicate",
        "refund",
        "held_released_settlement",
        "amount_mismatch",
    }
    duplicate = next(row for row in selected if row.exception_type == "duplicate")
    assert duplicate.amount == 8_000


@pytest.mark.asyncio
async def test_completed_run_investigates_only_the_bounded_risk_portfolio(monkeypatch):
    _, _, run, _ = _session()
    rows = [
        SimpleNamespace(id=uuid4(), status=ExceptionStatus.open, exception_type=kind, amount=amount)
        for kind, amount in (
            ("ambiguous", 9_000),
            ("duplicate", 8_000),
            ("refund", 7_000),
            ("held_released_settlement", 6_000),
            ("amount_mismatch", 5_000),
        )
    ]
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        execute=AsyncMock(return_value=_Result(rows=rows)),
        commit=AsyncMock(),
    )
    investigate = AsyncMock(
        side_effect=lambda current_session, exception_id, provider=None: exception_id
    )
    monkeypatch.setattr(investigator_module, "investigate_exception", investigate)

    result = await investigate_completed_run(session, run.id)

    assert len(result) == 5
    assert investigate.await_count == 5
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_timeout_is_sanitized():
    async def handler(_request):
        raise httpx.ReadTimeout("secret-api-key=hidden")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="test-key", model="gemini-test", client=client)

    with pytest.raises(ProviderError) as error:
        await provider.investigate(InvestigationContext(
            exception_id=EXCEPTION_ID,
            batch_id=BATCH_ID,
            run_id=RUN_ID,
            exception_type="duplicate",
        ))

    assert error.value.code == "timeout"
    assert "hidden" not in str(error.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_429_is_reported_without_response_body():
    async def handler(_request):
        return httpx.Response(429, json={"error": {"message": "secret token leaked"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="test-key", model="gemini-test", client=client)

    with pytest.raises(ProviderError) as error:
        await provider.investigate(InvestigationContext(
            exception_id=EXCEPTION_ID,
            batch_id=BATCH_ID,
            run_id=RUN_ID,
            exception_type="duplicate",
        ))

    assert error.value.code == "rate_limited"
    assert "secret" not in str(error.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_malformed_json_is_rejected():
    async def handler(_request):
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="test-key", model="gemini-test", client=client)

    with pytest.raises(ProviderError) as error:
        await provider.investigate(InvestigationContext(
            exception_id=EXCEPTION_ID,
            batch_id=BATCH_ID,
            run_id=RUN_ID,
            exception_type="duplicate",
        ))

    assert error.value.code == "malformed_response"
    await client.aclose()
