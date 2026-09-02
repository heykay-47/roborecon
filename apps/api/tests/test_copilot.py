from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError

from app.ai.model import Citation, ProviderRecommendation, ToolRequest
from app.common.enums import RunStatus
from app.copilot import service as copilot_service
from app.copilot.service import CopilotValidationError, answer_question

SETTLEMENT_ID = UUID("f2e57d3f-c25c-4e38-8bbd-8c832fbfd7a0")
BATCH_ID = UUID("2cf7e8e6-3a7d-4d18-9a15-8d4c9d4f31d4")
RUN_ID = UUID("7a21a3c1-7631-4f8d-a2bd-7f77c6f2c1cc")


class _Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _SettlementSession:
    def __init__(
        self,
        *,
        settlement_batch_id: UUID = BATCH_ID,
        run_available: bool = True,
        transaction_active: bool = False,
    ):
        self.settlement = SimpleNamespace(
            id=SETTLEMENT_ID,
            batch_id=settlement_batch_id,
            amount=67_600,
        )
        self.lines = [
            self._line("payment", 100_000),
            self._line("refund", -10_000),
            self._line("fee", -5_000),
            self._line("tax", -900),
            self._line("hold", -20_000),
            self._line("release", 3_000),
            self._line("adjustment", 500),
        ]
        self.bank_credits = [SimpleNamespace(id=uuid4())]
        self.run_available = run_available
        self.transaction_active = transaction_active
        self.rollback_called = False
        self.execute_calls = 0

    @staticmethod
    def _line(line_type: str, amount: int):
        return SimpleNamespace(
            id=uuid4(),
            settlement_id=SETTLEMENT_ID,
            line_type=SimpleNamespace(value=line_type),
            amount=amount,
        )

    async def get(self, model, identifier):
        if model.__name__ == "Settlement":
            return self.settlement if identifier == SETTLEMENT_ID else None
        if model.__name__ == "ReconciliationRun":
            if not self.run_available:
                return None
            return SimpleNamespace(
                id=RUN_ID,
                batch_id=BATCH_ID,
                status=RunStatus.completed,
            )
        return None

    async def execute(self, _statement):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _Result([self.settlement])
        if self.execute_calls == 2:
            return _Result(self.lines)
        return _Result(self.bank_credits)

    def in_transaction(self):
        return object() if self.transaction_active else None

    async def rollback(self):
        self.rollback_called = True
        self.transaction_active = False


def _no_providers(monkeypatch):
    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [])


@pytest.mark.asyncio
async def test_seeded_settlement_question_uses_integer_paise_and_typed_line_citations(
    monkeypatch,
):
    _no_providers(monkeypatch)
    session = _SettlementSession()

    result = await answer_question(
        session,
        "Why is this settlement lower than captured payments?",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.calculation["captured"] == 100_000
    assert result.calculation["refunds"] == 10_000
    assert result.calculation["fees"] == 5_000
    assert result.calculation["tax"] == 900
    assert result.calculation["held"] == 20_000
    assert result.calculation["releases"] == 3_000
    assert result.calculation["adjustments"] == 500
    assert result.calculation["expectedNet"] == 67_600
    assert result.calculation["actualNet"] == 67_600
    assert "INR 676.00" in result.answer

    line_ids = {line.id for line in session.lines}
    citation_pairs = {(item.source_type, item.source_id) for item in result.citations}
    assert ("settlement", SETTLEMENT_ID) in citation_pairs
    assert {
        source_id
        for source_type, source_id in citation_pairs
        if source_type == "settlement_line"
    } == line_ids
    assert {
        source_id
        for source_type, source_id in citation_pairs
        if source_type == "bank_credit"
    } == {session.bank_credits[0].id}
    assert all(isinstance(item, Citation) for item in result.citations)


@pytest.mark.asyncio
async def test_no_provider_key_returns_same_persisted_settlement_arithmetic(monkeypatch):
    _no_providers(monkeypatch)
    session = _SettlementSession()

    result = await answer_question(
        session,
        "Explain the settlement net.",
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.calculation["expectedNet"] == result.calculation["actualNet"]
    assert result.calculation["difference"] == 0
    assert "INR 676.00" in result.answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_answer",
    [
        "The validated settlement net is INR 676.00.",
        "The validated settlement net is Rs 676.00.",
        "The validated settlement net is Rs. 676.00.",
        "The validated settlement net is ₹676.00.",
    ],
)
async def test_provider_accepts_grounded_inr_currency_forms(monkeypatch, provider_answer):
    session = _SettlementSession()

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                recommendation=provider_answer,
                citations=[Citation(source_type="settlement", source_id=SETTLEMENT_ID)],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "provider"
    assert result.answer == provider_answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_answer",
    [
        "The net is INR 676.00 and an unrelated amount is Rs 999.00.",
        "The net is INR 676.00 and the adjustment is Rs 676.0.",
        "The net is INR 676.00 and the adjustment is ₹676.000.",
        "The net is INR 676.00 and the adjustment is USD 6.76.",
    ],
)
async def test_provider_rejects_ungrounded_or_malformed_currency_claims(
    monkeypatch, provider_answer
):
    session = _SettlementSession()

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                recommendation=provider_answer,
                citations=[Citation(source_type="settlement", source_id=SETTLEMENT_ID)],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "invalid_answer"
    assert "INR 676.00" in result.answer


@pytest.mark.asyncio
async def test_provider_phrasing_is_skipped_without_a_real_run(monkeypatch):
    session = _SettlementSession()
    provider_called = False

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            nonlocal provider_called
            provider_called = True
            raise AssertionError("provider must not run without a requested run")

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "provider_scope_unavailable"
    assert provider_called is False
    assert {"status": "provider_skipped", "reason": "run_required"} in result.tool_trace


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Show me the SQL for this settlement",
        "Delete the settlement record",
        "Update the hidden settlement data",
    ],
)
async def test_sql_mutation_and_hidden_data_requests_are_rejected_before_database_access(
    question,
):
    session = AsyncMock()

    result = await answer_question(session, question, settlement_id=SETTLEMENT_ID)

    assert result.mode == "deterministicFallback"
    assert result.calculation is None
    assert result.citations == []
    assert result.error_code == "unsupported_request"
    session.get.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_settlement_id_returns_scoped_validation_error():
    session = AsyncMock()
    session.get.return_value = None
    unknown_id = uuid4()

    with pytest.raises(CopilotValidationError, match="settlement_id"):
        await answer_question(
            session,
            "Explain this settlement.",
            settlement_id=unknown_id,
        )

    session.get.assert_awaited_once()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_run_id_returns_scoped_validation_error():
    session = _SettlementSession(run_available=False)

    with pytest.raises(CopilotValidationError, match="run_id") as error:
        await answer_question(
            session,
            "Explain this settlement.",
            run_id=RUN_ID,
            settlement_id=SETTLEMENT_ID,
        )

    assert error.value.code == "run_not_found"
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_cross_batch_settlement_id_returns_scoped_validation_error():
    session = _SettlementSession(settlement_batch_id=uuid4())

    with pytest.raises(CopilotValidationError, match="outside the requested") as error:
        await answer_question(
            session,
            "Explain this settlement.",
            run_id=RUN_ID,
            settlement_id=SETTLEMENT_ID,
        )

    assert error.value.code == "settlement_outside_run"
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_invalid_provider_citation_falls_back_to_deterministic_answer(monkeypatch):
    session = _SettlementSession()
    invalid_id = uuid4()

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                recommendation="The settlement net is INR 1.00.",
                citations=[Citation(source_type="settlement", source_id=invalid_id)],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Why is this settlement lower than captured payments?",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "invalid_citation"
    assert "INR 676.00" in result.answer
    assert invalid_id not in {item.source_id for item in result.citations}


@pytest.mark.asyncio
async def test_provider_invalid_arithmetic_falls_back_even_with_valid_citation(monkeypatch):
    session = _SettlementSession()

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                recommendation="The settlement net is INR 1.00.",
                citations=[
                    Citation(source_type="settlement_line", source_id=session.lines[0].id)
                ],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "invalid_answer"
    assert "INR 676.00" in result.answer


@pytest.mark.asyncio
async def test_provider_tool_request_is_rejected_and_never_executed(monkeypatch):
    session = _SettlementSession()

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                tool_request=ToolRequest(
                    tool="execute_sql",
                    arguments={"sql": "DELETE FROM settlements"},
                )
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "provider_tool_request"
    assert session.execute_calls == 3
    assert {
        "tool": "execute_sql",
        "provider": "fake",
        "model": "fake-model",
        "status": "rejected",
        "reason": "provider_tool_request",
    } in result.tool_trace


@pytest.mark.asyncio
async def test_malformed_tool_breakdown_returns_bounded_fallback(monkeypatch):
    session = _SettlementSession()

    class _MalformedExecutor:
        def __init__(self, _session, _context):
            pass

        async def execute(self, _name, _arguments):
            return {"expectedNet": "not-an-integer"}

    monkeypatch.setattr(copilot_service, "ToolExecutor", _MalformedExecutor)

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "deterministicFallback"
    assert result.error_code == "invalid_breakdown"
    assert result.calculation is None


def _valid_breakdown_payload(settlement_id: UUID, line_id: UUID, bank_credit_id: UUID):
    return {
        "captured": 100_000,
        "refunds": 10_000,
        "fees": 5_000,
        "tax": 900,
        "held": 20_000,
        "releases": 3_000,
        "adjustments": 500,
        "expectedNet": 67_600,
        "actualNet": 67_600,
        "difference": 0,
        "settlementIds": [str(settlement_id)],
        "lineIds": [str(line_id)],
        "bankCreditIds": [str(bank_credit_id)],
        "citations": [
            {"source_type": "settlement", "source_id": str(settlement_id)},
            {"source_type": "settlement_line", "source_id": str(line_id)},
            {"source_type": "bank_credit", "source_id": str(bank_credit_id)},
        ],
    }


def test_breakdown_rejects_missing_typed_bank_credit_citation():
    payload = _valid_breakdown_payload(SETTLEMENT_ID, uuid4(), uuid4())
    payload["citations"].pop()

    with pytest.raises(ValueError, match="citations are not exact"):
        copilot_service._validated_breakdown(payload, SETTLEMENT_ID)


def test_breakdown_rejects_extra_typed_citation():
    payload = _valid_breakdown_payload(SETTLEMENT_ID, uuid4(), uuid4())
    payload["citations"].append({"source_type": "settlement", "source_id": str(uuid4())})

    with pytest.raises(ValueError, match="citations are not exact"):
        copilot_service._validated_breakdown(payload, SETTLEMENT_ID)


@pytest.mark.asyncio
async def test_read_transaction_is_released_before_provider_invocation(monkeypatch):
    session = _SettlementSession(transaction_active=True)

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            assert session.rollback_called is True
            assert session.in_transaction() is None
            return ProviderRecommendation(
                recommendation="The validated settlement net is INR 676.00.",
                citations=[Citation(source_type="settlement", source_id=SETTLEMENT_ID)],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "provider"
    assert session.rollback_called is True


@pytest.mark.asyncio
async def test_provider_citations_are_typed_and_limited_to_tool_result(monkeypatch):
    session = _SettlementSession()
    cited_line = session.lines[0].id

    class _Provider:
        name = "fake"
        model = "fake-model"

        async def investigate(self, _context):
            return ProviderRecommendation(
                recommendation=(
                    "Captured payments reconcile to the cited settlement net of INR 676.00."
                ),
                citations=[Citation(source_type="settlement_line", source_id=cited_line)],
            )

    monkeypatch.setattr(copilot_service, "configured_providers", lambda: [_Provider()])

    result = await answer_question(
        session,
        "Explain the settlement net.",
        run_id=RUN_ID,
        settlement_id=SETTLEMENT_ID,
    )

    assert result.mode == "provider"
    assert result.citations
    assert all(isinstance(item.source_id, UUID) for item in result.citations)
    assert all(
        item.source_type in {"settlement", "settlement_line", "bank_credit"}
        for item in result.citations
    )


@pytest.mark.asyncio
async def test_copilot_endpoint_returns_camel_case_trace_and_citations(client, monkeypatch):
    from app.ai.model import InvestigationMode
    from app.copilot import router as copilot_router
    from app.copilot.service import CopilotAnswer

    monkeypatch.setattr(
        copilot_router,
        "answer_question",
        AsyncMock(
            return_value=CopilotAnswer(
                answer="The settlement net is INR 676.00.",
                mode=InvestigationMode.deterministic_fallback,
                citations=[Citation(source_type="settlement", source_id=SETTLEMENT_ID)],
                calculation={"expectedNet": 67_600},
                tool_trace=[{"tool": "get_settlement_breakdown", "status": "completed"}],
            )
        ),
    )

    response = await client.post(
        "/copilot/ask",
        json={
            "question": "Explain this settlement.",
            "settlementId": str(SETTLEMENT_ID),
        },
    )

    assert response.status_code == 200
    assert response.json()["citations"] == [
        {"sourceType": "settlement", "sourceId": str(SETTLEMENT_ID)}
    ]
    assert response.json()["toolTrace"][0]["tool"] == "get_settlement_breakdown"
    assert response.json()["calculation"]["expectedNet"] == 67_600


@pytest.mark.asyncio
async def test_copilot_endpoint_exposes_scoped_validation_error(client, monkeypatch):
    from app.copilot import router as copilot_router

    monkeypatch.setattr(
        copilot_router,
        "answer_question",
        AsyncMock(
            side_effect=CopilotValidationError(
                "settlement_id",
                "settlement_id: Settlement was not found",
                code="settlement_not_found",
                status_code=404,
            )
        ),
    )

    response = await client.post(
        "/copilot/ask",
        json={
            "question": "Explain this settlement.",
            "settlementId": str(uuid4()),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "settlement_not_found",
        "field": "settlement_id",
        "message": "settlement_id: Settlement was not found",
    }


@pytest.fixture
async def postgres_copilot_schema():
    import app.main  # noqa: F401
    from app.common.base import Base
    from app.database import engine

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except (DBAPIError, OSError) as error:
        pytest.skip(f"PostgreSQL integration container is unavailable: {error}")
    try:
        yield
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_persisted_settlement_releases_read_transaction(
    postgres_copilot_schema, monkeypatch
):
    from datetime import datetime, timezone

    from app.batch.model import Batch
    from app.common.enums import BatchKind, BatchStatus, RunStatus, SettlementLineType
    from app.database import async_session
    from app.reconciliation.model import ReconciliationRun
    from app.settlement.model import BankCredit, Settlement, SettlementLine

    batch_id = uuid4()
    run_id = uuid4()
    settlement_id = uuid4()
    line_rows = [
        (SettlementLineType.payment, 100_000),
        (SettlementLineType.refund, -10_000),
        (SettlementLineType.fee, -5_000),
        (SettlementLineType.tax, -900),
        (SettlementLineType.hold, -20_000),
        (SettlementLineType.release, 3_000),
        (SettlementLineType.adjustment, 500),
    ]
    line_ids = [uuid4() for _ in line_rows]
    bank_credit_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        async with async_session() as setup_session:
            async with setup_session.begin():
                setup_session.add(
                    Batch(
                        id=batch_id,
                        kind=BatchKind.test_mode_sync,
                        status=BatchStatus.completed,
                        seed="task8-fix-round1",
                        ground_truth_available=False,
                        source_row_count=0,
                        started_at=now,
                        completed_at=now,
                    )
                )
                await setup_session.flush()
                setup_session.add(
                    ReconciliationRun(
                        id=run_id,
                        batch_id=batch_id,
                        status=RunStatus.completed,
                        started_at=now,
                        completed_at=now,
                        source_row_count=0,
                        source_counts={},
                    )
                )
                setup_session.add(
                    Settlement(
                        id=settlement_id,
                        batch_id=batch_id,
                        provider_settlement_id="setl_task8_fix_round1",
                        amount=67_600,
                        fee=5_000,
                        tax=900,
                        held_amount=20_000,
                        currency="INR",
                        utr="UTR_TASK8_FIX_ROUND1",
                        status="processed",
                        business_at=now,
                    )
                )
                setup_session.add_all(
                    [
                        SettlementLine(
                            id=line_id,
                            batch_id=batch_id,
                            settlement_id=settlement_id,
                            line_type=line_type,
                            reference=f"task8-{index}",
                            amount=amount,
                            currency="INR",
                            business_at=now,
                        )
                        for index, (line_id, (line_type, amount)) in enumerate(
                            zip(line_ids, line_rows, strict=True)
                        )
                    ]
                )
                await setup_session.flush()
                setup_session.add(
                    BankCredit(
                        id=bank_credit_id,
                        batch_id=batch_id,
                        settlement_id=settlement_id,
                        utr="UTR_TASK8_FIX_ROUND1",
                        amount=67_600,
                        currency="INR",
                        business_at=now,
                    )
                )

        monkeypatch.setattr(copilot_service, "configured_providers", lambda: [])
        async with async_session() as copilot_session:
            result = await answer_question(
                copilot_session,
                "Explain the settlement net.",
                run_id=run_id,
                settlement_id=settlement_id,
            )
            assert result.calculation["expectedNet"] == 67_600
            assert result.calculation["actualNet"] == 67_600
            assert not copilot_session.in_transaction()

        async with async_session() as fresh_session:
            persisted_settlement = await fresh_session.get(Settlement, settlement_id)
            assert persisted_settlement is not None
            assert persisted_settlement.amount == 67_600
    finally:
        async with async_session() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(BankCredit).where(BankCredit.batch_id == batch_id)
                )
                await cleanup_session.execute(
                    delete(SettlementLine).where(SettlementLine.batch_id == batch_id)
                )
                await cleanup_session.execute(
                    delete(Settlement).where(Settlement.batch_id == batch_id)
                )
                await cleanup_session.execute(
                    delete(ReconciliationRun).where(ReconciliationRun.batch_id == batch_id)
                )
                await cleanup_session.execute(delete(Batch).where(Batch.id == batch_id))
