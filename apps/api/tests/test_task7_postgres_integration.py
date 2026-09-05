from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.fixture
async def postgres_schema():
    from app.database import engine
    from app.database_init import initialize_database

    try:
        await initialize_database()
    except (DBAPIError, OSError) as exc:
        pytest.skip(f"PostgreSQL integration container is unavailable: {exc}")
    try:
        yield
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_migration_repairs_duplicate_global_sequences(
    postgres_schema,
):
    from app.database import engine
    from app.database_init import _ensure_audit_event_sequence_index

    event_ids = [UUID(int=101), UUID(int=102), UUID(int=103)]
    occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text("DROP INDEX IF EXISTS uq_audit_event_scope_sequence")
            )
            for event_id, sequence, event_time in (
                (event_ids[0], 9, occurred_at + timedelta(seconds=1)),
                (event_ids[1], 9, occurred_at + timedelta(seconds=2)),
                (event_ids[2], 3, occurred_at + timedelta(seconds=3)),
            ):
                await connection.execute(
                    text(
                        """
                        INSERT INTO audit_events
                            (id, batch_id, event_type, sequence, actor,
                             entity_type, entity_id, occurred_at, summary)
                        VALUES
                            (:id, NULL, 'review_rejected', :sequence, 'test',
                             'test', NULL, :occurred_at, 'migration test')
                        """
                    ),
                    {
                        "id": event_id,
                        "sequence": sequence,
                        "occurred_at": event_time,
                    },
                )

            await _ensure_audit_event_sequence_index(connection)

            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT id, sequence
                        FROM audit_events
                        WHERE id IN (:first, :second, :third)
                        ORDER BY sequence
                        """
                    ),
                    {
                        "first": event_ids[0],
                        "second": event_ids[1],
                        "third": event_ids[2],
                    },
                )
            ).all()
            assert [(row.id, row.sequence) for row in rows] == [
                (event_ids[2], 1),
                (event_ids[0], 2),
                (event_ids[1], 3),
            ]

            index_exists = (
                await connection.execute(
                    text(
                        """
                        SELECT 1
                        FROM pg_indexes
                        WHERE tablename = 'audit_events'
                          AND indexname = 'uq_audit_event_scope_sequence'
                        """
                    )
                )
            ).scalar_one_or_none()
            assert index_exists == 1

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO audit_events
                                (id, batch_id, event_type, sequence, actor,
                                 entity_type, entity_id, occurred_at, summary)
                            VALUES
                                (:id, NULL, 'review_rejected', 1, 'test',
                                 'test', NULL, :occurred_at, 'duplicate test')
                            """
                        ),
                        {
                            "id": uuid4(),
                            "occurred_at": occurred_at,
                        },
                    )
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_postgres_review_persists_rejection_for_a_fresh_session(postgres_schema):
    from app.audit.model import AuditEvent
    from app.batch.model import Batch
    from app.common.enums import (
        BatchKind,
        BatchStatus,
        ExceptionStatus,
        ReconciliationStage,
        ResultStatus,
        ReviewAction,
        RunStatus,
    )
    from app.database import async_session
    from app.exception.service import review_exception
    from app.reconciliation.model import (
        ReconciliationException,
        ReconciliationResult,
        ReconciliationRun,
    )

    batch_id = uuid4()
    run_id = uuid4()
    result_id = uuid4()
    exception_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        async with async_session() as session:
            session.add(
                Batch(
                    id=batch_id,
                    kind=BatchKind.test_mode_sync,
                    status=BatchStatus.completed,
                    seed="task7-integration",
                    ground_truth_available=False,
                    source_row_count=0,
                    started_at=now,
                    completed_at=now,
                )
            )
            await session.flush()
            session.add(
                ReconciliationRun(
                    id=run_id,
                    batch_id=batch_id,
                    status=RunStatus.completed,
                    started_at=now,
                    completed_at=now,
                    source_row_count=0,
                    source_counts={},
                    metrics={
                        "open_exceptions": 1,
                        "financially_unresolved_cases": 1,
                        "money_reconciled": 0,
                        "money_unresolved": 1234,
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
            )
            await session.flush()
            session.add(
                ReconciliationResult(
                    id=result_id,
                    run_id=run_id,
                    batch_id=batch_id,
                    stage=ReconciliationStage.ledger_to_razorpay,
                    status=ResultStatus.ambiguous,
                    primary_source_type="ledger",
                    primary_source_id=None,
                    amount=1234,
                    currency="INR",
                    score=50,
                    runner_up_score=49,
                    margin=1,
                    autonomous=False,
                    selected_ids=[],
                    evidence=[],
                    candidates=[],
                )
            )
            await session.flush()
            session.add(
                ReconciliationException(
                    id=exception_id,
                    run_id=run_id,
                    result_id=result_id,
                    batch_id=batch_id,
                    status=ExceptionStatus.open,
                    exception_type="ambiguous",
                    source_type=None,
                    source_id=None,
                    amount=1234,
                    message="Integration review",
                )
            )
            await session.commit()

        async with async_session() as review_session:
            decision = await review_exception(
                review_session,
                exception_id,
                ReviewAction.reject,
                None,
                "No provider match",
                "integration-analyst",
            )
            assert decision.status is ExceptionStatus.rejected

        async with async_session() as fresh_session:
            persisted_run = await fresh_session.get(ReconciliationRun, run_id)
            persisted_result = await fresh_session.get(
                ReconciliationResult, result_id
            )
            persisted_exception = await fresh_session.get(
                ReconciliationException, exception_id
            )
            events = (
                await fresh_session.execute(
                    text(
                        """
                        SELECT sequence, actor, event_type
                        FROM audit_events
                        WHERE batch_id = :batch_id
                        ORDER BY sequence
                        """
                    ),
                    {"batch_id": batch_id},
                )
            ).all()

            assert persisted_exception.status is ExceptionStatus.rejected
            assert persisted_result.status is ResultStatus.confirmed_no_match
            assert persisted_run.metrics["money_unresolved"] == 1234
            assert persisted_run.metrics["review_adjusted"]["rejectedCases"] == 1
            assert [(row.sequence, row.actor) for row in events] == [
                (1, "integration-analyst")
            ]
            assert events[0].event_type == "review_rejected"
    finally:
        async with async_session() as cleanup_session:
            async with cleanup_session.begin():
                await cleanup_session.execute(
                    delete(AuditEvent).where(AuditEvent.batch_id == batch_id)
                )
                await cleanup_session.execute(
                    delete(ReconciliationException).where(
                        ReconciliationException.batch_id == batch_id
                    )
                )
                await cleanup_session.execute(
                    delete(ReconciliationResult).where(
                        ReconciliationResult.batch_id == batch_id
                    )
                )
                await cleanup_session.execute(
                    delete(ReconciliationRun).where(
                        ReconciliationRun.batch_id == batch_id
                    )
                )
                await cleanup_session.execute(
                    delete(Batch).where(Batch.id == batch_id)
                )
