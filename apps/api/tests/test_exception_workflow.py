import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.common.enums import ExceptionStatus, ResultStatus, ReviewAction
from app.reconciliation import model as reconciliation_model
from app.reconciliation.model import ReconciliationException, ReconciliationResult


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _Result:
    def __init__(self, *, scalar_one_or_none=None, rows=()):
        self._scalar_one_or_none = scalar_one_or_none
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


def _review_context(*, status=ExceptionStatus.open):
    batch_id = uuid4()
    run_id = uuid4()
    exception_id = uuid4()
    result_id = uuid4()
    candidate_id = uuid4()
    result = ReconciliationResult(
        id=result_id,
        run_id=run_id,
        batch_id=batch_id,
        stage="ledger_to_razorpay",
        status=ResultStatus.ambiguous,
        primary_source_type="ledger",
        primary_source_id=uuid4(),
        amount=12_345,
        currency="INR",
        score=88,
        runner_up_score=82,
        margin=6,
        autonomous=False,
        selected_ids=[],
        evidence=[{"rule_code": "reference", "points": 88}],
        candidates=[
            {
                "candidate_id": str(candidate_id),
                "source_type": "razorpay_payment",
                "score": 88,
                "evidence": [{"rule_code": "reference", "points": 88}],
                "contradictions": [],
                "duplicate": False,
                "exact_identifier_chain": False,
                "verified_settlement_math": False,
            }
        ],
    )
    exception = ReconciliationException(
        id=exception_id,
        run_id=run_id,
        result_id=result_id,
        batch_id=batch_id,
        status=status,
        exception_type="ambiguous",
        source_type="ledger",
        source_id=result.primary_source_id,
        amount=result.amount,
        message="Deterministic outcome requires review: ambiguous.",
        created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    run = SimpleNamespace(
        id=run_id,
        batch_id=batch_id,
        metrics={
            "open_exceptions": 1,
            "financially_unresolved_cases": 1,
            "money_reconciled": 0,
            "money_unresolved": result.amount,
            "review_adjusted": {
                "closedCases": 0,
                "reviewedCases": 0,
                "approvedCases": 0,
                "rejectedCases": 0,
                "resolvedCases": 0,
                "moneyReconciled": 0,
            },
        },
    )
    source = SimpleNamespace(id=candidate_id, batch_id=batch_id)
    return exception, result, run, source


def _session(
    exception,
    result,
    run,
    source,
    *,
    second_rows=None,
    include_locked_run=True,
):
    session = AsyncMock()
    session.begin = MagicMock(return_value=_Transaction())
    execute_results = [
        _Result(scalar_one_or_none=exception),
        _Result(rows=[source] if second_rows is None else second_rows),
    ]
    if include_locked_run:
        execute_results.append(_Result(scalar_one_or_none=run))
    execute_results.append(_Result(scalar_one_or_none=None))
    session.execute = AsyncMock(
        side_effect=execute_results
    )
    session.get = AsyncMock(side_effect=lambda model, identifier: {
        ReconciliationResult: result,
        reconciliation_model.ReconciliationRun: run,
    }.get(model))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_audit_append_preserves_sequence_actor_and_source_context():
    from app.audit.service import append_event
    from app.common.enums import AuditEventType

    batch_id = uuid4()
    source_id = uuid4()
    session = AsyncMock()
    batch_result = MagicMock(
        scalar_one_or_none=lambda: SimpleNamespace(id=batch_id),
        scalar_one=lambda: 12,
    )
    sequence_result = MagicMock(scalar_one=lambda: 12)
    session.execute = AsyncMock(side_effect=[batch_result, sequence_result])
    session.add = MagicMock()

    event = await append_event(
        session,
        batch_id=batch_id,
        event_type=AuditEventType.review_rejected,
        entity_type="reconciliation_exception",
        entity_id=uuid4(),
        summary="Exception rejected by human review",
        actor="analyst-7",
        source_type="ledger",
        source_id=source_id,
    )

    assert event.sequence == 13
    assert event.actor == "analyst-7"
    assert event.source_type == "ledger"
    assert event.source_id == source_id
    session.add.assert_called_once_with(event)
    assert session.execute.await_count == 2
    assert session.execute.call_args_list[0].args[0]._for_update_arg is not None


@pytest.mark.asyncio
async def test_audit_append_locks_null_scope_with_transaction_advisory_lock():
    from app.audit.service import append_event
    from app.common.enums import AuditEventType

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[MagicMock(), MagicMock(scalar_one=lambda: 4)]
    )
    session.add = MagicMock()

    event = await append_event(
        session,
        batch_id=None,
        event_type=AuditEventType.review_rejected,
        entity_type="reconciliation_exception",
        entity_id=uuid4(),
        summary="Exception rejected by human review",
    )

    assert event.sequence == 5
    assert session.execute.await_count == 2
    assert "pg_advisory_xact_lock" in str(session.execute.call_args_list[0].args[0])


@pytest.mark.asyncio
async def test_audit_listing_applies_event_type_filter_in_sql():
    from app.audit.service import list_events
    from app.common.enums import AuditEventType

    count_result = MagicMock(scalar=lambda: 1)
    rows_result = MagicMock(scalars=lambda: MagicMock(all=lambda: []))
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, rows_result])

    rows, total = await list_events(
        session,
        event_type=AuditEventType.ai_recommendation,
    )

    assert rows == []
    assert total == 1
    assert "audit_events.event_type" in str(session.execute.call_args_list[0].args[0])


@pytest.mark.asyncio
async def test_audit_sequence_migration_sql_repairs_and_uniquifies_both_scopes():
    from app.main import _ensure_audit_event_sequence_index

    class _Connection:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(str(statement))

    connection = _Connection()

    await _ensure_audit_event_sequence_index(connection)

    sql = "\n".join(connection.statements).lower()
    assert "row_number()" in sql
    assert "partition by batch_id" in sql
    assert "order by sequence, occurred_at, id" in sql
    assert "coalesce(batch_id::text" in sql
    assert "create unique index" in sql


def test_audit_event_batch_sequence_is_unique():
    from app.audit.model import AuditEvent

    assert any(
        constraint.name == "uq_audit_event_batch_sequence"
        for constraint in AuditEvent.__table__.constraints
    )


@pytest.mark.asyncio
async def test_approve_creates_one_human_link_and_preserves_deterministic_evidence(
    monkeypatch,
):
    from app.audit import service as audit_service
    from app.exception.service import review_exception

    exception, result, run, source = _review_context()
    session = _session(exception, result, run, source)
    original_evidence = copy.deepcopy(result.evidence)
    original_candidates = copy.deepcopy(result.candidates)
    append_event = AsyncMock()
    monkeypatch.setattr(audit_service, "append_event", append_event)

    decision = await review_exception(
        session,
        exception.id,
        ReviewAction.approve,
        source.id,
        "Verified against provider receipt",
        "analyst-7",
    )

    links = [
        item
        for item in (call.args[0] for call in session.add.call_args_list)
        if isinstance(item, reconciliation_model.MatchLink)
    ]
    assert decision.status is ExceptionStatus.approved
    assert exception.status is ExceptionStatus.approved
    assert len(links) == 1
    assert links[0].source_id == source.id
    assert links[0].autonomous is False
    assert links[0].actor == "analyst-7"
    assert result.autonomous is False
    assert result.evidence == original_evidence
    assert result.candidates == original_candidates
    assert run.metrics["open_exceptions"] == 0
    assert run.metrics["money_reconciled"] == result.amount
    assert run.metrics["money_unresolved"] == 0
    append_event.assert_awaited_once()
    assert append_event.call_args.kwargs["source_id"] == source.id


@pytest.mark.asyncio
async def test_reject_closes_exception_without_link_and_keeps_money_unresolved(
    monkeypatch,
):
    from app.audit import service as audit_service
    from app.exception.service import review_exception

    exception, result, run, source = _review_context()
    session = _session(exception, result, run, source, second_rows=[])
    append_event = AsyncMock()
    monkeypatch.setattr(audit_service, "append_event", append_event)

    decision = await review_exception(
        session,
        exception.id,
        ReviewAction.reject,
        None,
        "Provider record is not the ledger payment",
        "analyst-7",
    )

    links = [
        item
        for item in (call.args[0] for call in session.add.call_args_list)
        if isinstance(item, reconciliation_model.MatchLink)
    ]
    assert decision.status is ExceptionStatus.rejected
    assert exception.status is ExceptionStatus.rejected
    assert result.status is ResultStatus.confirmed_no_match
    assert links == []
    assert run.metrics["open_exceptions"] == 0
    assert run.metrics["money_reconciled"] == 0
    assert run.metrics["money_unresolved"] == result.amount
    append_event.assert_awaited_once()
    assert append_event.call_args.kwargs["source_id"] == exception.source_id


@pytest.mark.asyncio
async def test_reject_removes_provisional_links_but_preserves_human_links(monkeypatch):
    from app.audit import service as audit_service
    from app.exception.service import review_exception

    exception, result, run, source = _review_context()
    provisional = reconciliation_model.MatchLink(
        id=uuid4(),
        run_id=run.id,
        result_id=result.id,
        source_type="ledger",
        source_id=uuid4(),
        role="selected",
        autonomous=False,
        actor="system",
    )
    human = reconciliation_model.MatchLink(
        id=uuid4(),
        run_id=run.id,
        result_id=result.id,
        source_type="razorpay_payment",
        source_id=source.id,
        role="human_approved",
        autonomous=False,
        actor="analyst-1",
    )
    session = _session(
        exception,
        result,
        run,
        source,
        second_rows=[provisional, human],
    )
    monkeypatch.setattr(audit_service, "append_event", AsyncMock())

    await review_exception(
        session,
        exception.id,
        ReviewAction.reject,
        None,
        "No provider match",
        "analyst-7",
    )

    session.delete.assert_awaited_once_with(provisional)
    assert human not in [call.args[0] for call in session.delete.call_args_list]


@pytest.mark.asyncio
async def test_approve_preserves_unavailable_benchmark_money_metrics(monkeypatch):
    from app.audit import service as audit_service
    from app.exception.service import review_exception

    exception, result, run, source = _review_context()
    run.metrics.update(
        {
            "financially_unresolved_cases": None,
            "money_reconciled": None,
            "money_unresolved": None,
            "review_adjusted": {
                "closedCases": 0,
                "reviewedCases": 0,
                "approvedCases": 0,
                "rejectedCases": 0,
                "resolvedCases": 0,
                "moneyReconciled": None,
            },
        }
    )
    session = _session(exception, result, run, source)
    monkeypatch.setattr(audit_service, "append_event", AsyncMock())

    await review_exception(
        session,
        exception.id,
        ReviewAction.approve,
        source.id,
        "Verified",
        "analyst-7",
    )

    assert run.metrics["open_exceptions"] == 0
    assert run.metrics["review_adjusted"]["approvedCases"] == 1
    assert run.metrics["review_adjusted"]["resolvedCases"] == 1
    assert run.metrics["review_adjusted"]["moneyReconciled"] is None
    assert run.metrics["money_reconciled"] is None
    assert run.metrics["money_unresolved"] is None


@pytest.mark.asyncio
async def test_approve_assigns_metrics_copy_and_locks_run_row(monkeypatch):
    from app.audit import service as audit_service
    from app.exception.service import review_exception

    exception, result, run, source = _review_context()
    original_metrics = run.metrics
    session = _session(
        exception,
        result,
        run,
        source,
        include_locked_run=True,
    )
    monkeypatch.setattr(audit_service, "append_event", AsyncMock())

    await review_exception(
        session,
        exception.id,
        ReviewAction.approve,
        source.id,
        "Verified",
        "analyst-7",
    )

    assert run.metrics is not original_metrics
    locked_statements = [
        call.args[0]
        for call in session.execute.call_args_list
        if getattr(call.args[0], "_for_update_arg", None) is not None
    ]
    assert len(locked_statements) == 2


@pytest.mark.asyncio
async def test_terminal_review_returns_conflict_without_mutating_records(monkeypatch):
    from app.audit import service as audit_service
    from app.exception.service import ReviewConflict, review_exception

    exception, result, run, source = _review_context(status=ExceptionStatus.approved)
    session = _session(exception, result, run, source)
    monkeypatch.setattr(audit_service, "append_event", AsyncMock())
    original_status = exception.status
    original_candidates = copy.deepcopy(result.candidates)

    with pytest.raises(ReviewConflict):
        await review_exception(
            session,
            exception.id,
            ReviewAction.reject,
            None,
            "Attempted second decision",
            "analyst-8",
        )

    assert exception.status is original_status
    assert result.candidates == original_candidates
    assert session.add.call_count == 0


@pytest.mark.asyncio
async def test_review_rejects_candidate_outside_exception_batch(monkeypatch):
    from app.audit import service as audit_service
    from app.exception.service import InvalidReviewCandidate, review_exception

    exception, result, run, source = _review_context()
    source.batch_id = uuid4()
    session = _session(exception, result, run, source)
    monkeypatch.setattr(audit_service, "append_event", AsyncMock())

    with pytest.raises(InvalidReviewCandidate):
        await review_exception(
            session,
            exception.id,
            ReviewAction.approve,
            source.id,
            None,
            "analyst-7",
        )

    assert exception.status is ExceptionStatus.open
    assert session.add.call_count == 0


@pytest.mark.asyncio
async def test_exception_detail_skips_malformed_camel_case_candidate(monkeypatch):
    from app.exception.service import get_exception_detail

    exception, result, run, source = _review_context()
    exception.source_id = None
    result.selected_ids = ["not-a-uuid"]
    result.evidence = []
    result.candidates = [
        {
            "candidateId": "not-a-uuid",
            "score": 55,
            "evidence": [],
            "contradictions": [],
            "duplicate": False,
            "exact_identifier_chain": False,
            "verified_settlement_math": False,
        }
    ]
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _Result(scalar_one_or_none=exception),
            _Result(rows=[]),
            _Result(rows=[]),
            _Result(rows=[]),
        ]
    )
    session.get = AsyncMock(return_value=result)

    detail = await get_exception_detail(session, exception.id)

    assert detail.result is not None
    assert detail.result.candidates[0].candidate_id == "not-a-uuid"
