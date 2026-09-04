from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.ai.model import (
    BatchCloseContext,
    BatchCloseExceptionContext,
    BatchCloseProviderResponse,
)
from app.common.enums import ExceptionStatus, ReconciliationStage, RunStatus
from app.reconciliation.model import BatchCloseBrief, ReconciliationException, ReconciliationResult

RUN_ID = UUID("d5c84fc4-6f42-4b55-8e0f-77e4ccf92c7d")
BATCH_ID = UUID("4c4f7f9d-82de-4673-8a5d-a8dbf9e61a11")
EXCEPTION_IDS = (
    UUID("c3ff0d98-5ed8-5e1a-bf69-5a43a90dcbbb"),
    UUID("2a2e4c98-74df-4ad1-a4bb-d7e4c6c5d88a"),
)


def _context() -> BatchCloseContext:
    return BatchCloseContext(
        run_id=RUN_ID,
        batch_id=BATCH_ID,
        source_row_count=12,
        result_count=4,
        money_reconciled=50_000,
        money_unresolved=12_500,
        operational_metrics={"recordsProcessed": 12, "durationMs": 40},
        source_counts={"ledger": 2, "total": 12},
        result_summaries=[],
        open_exceptions=[
            BatchCloseExceptionContext(
                exception_id=exception_id,
                exception_type="amount_mismatch",
                stage="razorpay_to_settlement",
                status="open",
                amount=12_500 if index == 0 else 4_000,
                message="Review the persisted evidence.",
                rule_codes=["settlement_math"],
                contradiction_codes=["net_discrepancy"],
                citations=[{"exceptionId": str(exception_id)}],
            )
            for index, exception_id in enumerate(EXCEPTION_IDS)
        ],
    )


def _response(*exception_ids: UUID) -> BatchCloseProviderResponse:
    return BatchCloseProviderResponse(
        themes=[
            {
                "title": "Settlement discrepancy",
                "summary": "The settlement totals need review.",
                "exceptionIds": [str(exception_id) for exception_id in exception_ids],
                "reviewAction": "Review settlement arithmetic against the cited evidence.",
                "citations": [
                    {"exceptionId": str(exception_id)} for exception_id in exception_ids
                ],
            }
        ]
    )


def test_provider_response_requires_exact_open_exception_coverage():
    from app.reconciliation.close_brief import CloseBriefValidationError, validate_provider_response

    with pytest.raises(CloseBriefValidationError, match="coverage"):
        validate_provider_response(_response(EXCEPTION_IDS[0]), _context())

    with pytest.raises(CloseBriefValidationError, match="coverage"):
        validate_provider_response(
            _response(EXCEPTION_IDS[0], EXCEPTION_IDS[0], EXCEPTION_IDS[1]),
            _context(),
        )


def test_deterministic_fallback_groups_open_exceptions_and_cites_each_one():
    from app.reconciliation.close_brief import build_deterministic_fallback

    fallback = build_deterministic_fallback(_context(), error_code="timeout")

    assert fallback.mode == "deterministicFallback"
    assert fallback.error_code == "timeout"
    assert len(fallback.themes) == 1
    assert set(fallback.themes[0].exception_ids) == set(EXCEPTION_IDS)
    assert {citation.exception_id for citation in fallback.themes[0].citations} == set(
        EXCEPTION_IDS
    )


def test_deterministic_fallback_does_not_claim_ai_coverage():
    from app.reconciliation.close_brief import _artifact, build_deterministic_fallback

    context = _context()
    draft = build_deterministic_fallback(context, error_code="timeout")
    artifact = _artifact(SimpleNamespace(context=context), draft, duration_ms=1)

    assert artifact["ai_exception_count"] == 0
    assert artifact["ai_coverage"]["covered_exceptions"] == 0
    assert len(artifact["themes"]) == 1


def test_provider_context_has_no_truth_or_benchmark_fields():
    context = _context()

    serialized = context.model_dump(mode="json")
    assert "ground_truth" not in str(serialized).lower()
    assert "precision" not in str(serialized).lower()
    assert "false_positive" not in str(serialized).lower()


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Provider:
    name = "test-provider"
    model = "test-model"

    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.contexts = []

    async def assess_batch_close(self, context):
        self.calls += 1
        self.contexts.append(context)
        return self.response


def _assessment_session(run, results, exceptions, latest_reviewed_at=None):
    brief = None
    session = AsyncMock()
    session.begin = MagicMock(return_value=_Transaction())
    session.execute = AsyncMock(
        side_effect=[
            _Result(scalar=run),
            _Result(scalar=None),
            _Result(rows=results),
            _Result(rows=exceptions),
            _Result(scalar=run),
            _Result(scalar=latest_reviewed_at),
        ]
    )

    async def get(model, identifier):
        if model is BatchCloseBrief and brief is not None and identifier == brief.id:
            return brief
        return None

    async def flush():
        nonlocal brief
        if brief is None:
            brief = next(
                item
                for item in session.add.call_args_list[-1].args
                if isinstance(item, BatchCloseBrief)
            )
            if brief.id is None:
                brief.id = uuid4()

    session.get = AsyncMock(side_effect=get)
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=flush)
    return session


@pytest.mark.asyncio
async def test_assessment_persists_provider_brief_without_touching_run_records(monkeypatch):
    from app.audit import service as audit_service
    from app.reconciliation.close_brief import assess_batch_close

    result_id = uuid4()
    exception_id = EXCEPTION_IDS[0]
    run = SimpleNamespace(
        id=RUN_ID,
        batch_id=BATCH_ID,
        status=RunStatus.completed,
        source_row_count=12,
        source_counts={"ledger": 2, "total": 12},
        metrics={"precision": 99.0, "recordsProcessed": 12},
    )
    result = ReconciliationResult(
        id=result_id,
        run_id=RUN_ID,
        batch_id=BATCH_ID,
        stage="razorpay_to_settlement",
        status="amount_mismatch",
        primary_source_type="ledger",
        primary_source_id=uuid4(),
        amount=12_500,
        currency="INR",
        score=70,
        runner_up_score=60,
        margin=10,
        autonomous=False,
        selected_ids=[],
        evidence=[{"rule_code": "settlement_math"}],
        candidates=[{"contradictions": ["net_discrepancy"]}],
    )
    exception = ReconciliationException(
        id=exception_id,
        run_id=RUN_ID,
        result_id=result_id,
        batch_id=BATCH_ID,
        status=ExceptionStatus.open,
        exception_type="amount_mismatch",
        source_type="ledger",
        source_id=result.primary_source_id,
        amount=12_500,
        message="Review the persisted evidence.",
    )
    session = _assessment_session(run, [result], [exception])
    provider = _Provider(_response(exception_id))
    append_event = AsyncMock()
    monkeypatch.setattr(audit_service, "append_event", append_event)

    brief = await assess_batch_close(session, RUN_ID, actor=" analyst-7 ", provider=provider)

    assert provider.calls == 1
    assert provider.contexts[0].open_exceptions[0].exception_id == exception_id
    assert "precision" not in provider.contexts[0].prompt()
    assert brief.posture == "review required"
    assert brief.mode == "provider"
    assert brief.open_exception_count == 1
    assert brief.money_unresolved == 12_500
    assert brief.financial_records_changed == 0
    assert append_event.await_args.kwargs["tool_trace"]["financialRecordsChanged"] == 0


@pytest.mark.asyncio
async def test_clean_run_skips_provider_and_is_ready(monkeypatch):
    from app.reconciliation import close_brief as close_brief_module
    from app.reconciliation.close_brief import assess_batch_close

    run = SimpleNamespace(
        id=RUN_ID,
        batch_id=BATCH_ID,
        status=RunStatus.completed,
        source_row_count=12,
        source_counts={"total": 12},
        metrics={"recordsProcessed": 12},
    )
    session = _assessment_session(run, [], [])
    configured = MagicMock(side_effect=AssertionError("provider must not be configured"))
    monkeypatch.setattr(close_brief_module, "configured_providers", configured)
    monkeypatch.setattr(close_brief_module.audit_service, "append_event", AsyncMock())

    brief = await assess_batch_close(session, RUN_ID)

    assert brief.posture == "ready"
    assert brief.mode == "not required"
    assert brief.open_exception_count == 0
    configured.assert_not_called()


def test_money_reconciled_uses_the_ledger_stage_once():
    from app.reconciliation.close_brief import _money_totals

    ledger_result = SimpleNamespace(
        id=uuid4(),
        amount=12_500,
        status="matched",
        stage=ReconciliationStage.ledger_to_razorpay,
    )
    settlement_result = SimpleNamespace(
        id=uuid4(),
        amount=12_500,
        status="matched",
        stage=ReconciliationStage.razorpay_to_settlement,
    )

    money_reconciled, money_unresolved = _money_totals(
        [ledger_result, settlement_result], []
    )

    assert money_reconciled == 12_500
    assert money_unresolved == 0


@pytest.mark.asyncio
async def test_batch_close_falls_back_after_the_configured_provider_fails(monkeypatch):
    from app.ai.provider import ProviderError
    from app.reconciliation import close_brief as close_brief_module

    class FailingProvider:
        name = "first-provider"
        model = "first-model"

        async def assess_batch_close(self, context):
            raise ProviderError(self.name, self.model, "timeout")

    second = _Provider(_response(*EXCEPTION_IDS))
    monkeypatch.setattr(
        close_brief_module,
        "configured_providers",
        lambda: [FailingProvider(), second],
    )

    draft = await close_brief_module._generate_draft(_context(), None)

    assert draft.mode == "deterministicFallback"
    assert draft.error_code == "timeout"
    assert draft.provider == "first-provider"
    assert second.calls == 0


@pytest.mark.asyncio
async def test_batch_close_falls_back_before_exceeding_prompt_limit(monkeypatch):
    from app.reconciliation import close_brief as close_brief_module

    configured = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(close_brief_module, "configured_providers", configured)
    monkeypatch.setattr(close_brief_module.settings, "ai_max_batch_close_prompt_chars", 20)

    draft = await close_brief_module._generate_draft(_context(), None)

    assert draft.mode == "deterministicFallback"
    assert draft.error_code == "input_limit"
    configured.assert_not_called()


@pytest.mark.asyncio
async def test_brief_is_stale_when_a_review_lands_during_generation(monkeypatch):
    from app.reconciliation.close_brief import assess_batch_close

    run = SimpleNamespace(
        id=RUN_ID,
        batch_id=BATCH_ID,
        status=RunStatus.completed,
        source_row_count=12,
        source_counts={"total": 12},
        metrics={"recordsProcessed": 12},
    )
    reviewed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    session = _assessment_session(run, [], [], latest_reviewed_at=reviewed_at)
    monkeypatch.setattr(
        assess_batch_close.__globals__["audit_service"], "append_event", AsyncMock()
    )

    brief = await assess_batch_close(session, RUN_ID)

    assert brief.stale_at == reviewed_at
