import asyncio

from sqlalchemy import text

from app.ai.model import AIInvestigationRecord  # noqa: F401
from app.audit.model import AuditEvent  # noqa: F401
from app.batch.model import Batch, IngestionRecord  # noqa: F401
from app.common.base import Base
from app.common.code_sequence import CodeSequence  # noqa: F401
from app.database import engine
from app.evaluation.model import EvaluationCase, GroundTruthLink  # noqa: F401
from app.ledger.model import LedgerEntry  # noqa: F401
from app.razorpay.model import (  # noqa: F401
    RazorpayOrder,
    RazorpayPayment,
    RazorpayRefund,
)
from app.reconciliation.model import (  # noqa: F401
    BatchCloseBrief,
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine  # noqa: F401

_ADDITIONAL_AUDIT_EVENT_VALUES = (
    "razorpay_sync_started",
    "razorpay_sync_completed",
    "razorpay_sync_failed",
    "batch_close_brief_generated",
)

_TASK7_COLUMNS = (
    ("reconciliation_exceptions", "review_note", "TEXT"),
    ("reconciliation_exceptions", "reviewed_by", "VARCHAR(100)"),
    ("reconciliation_exceptions", "reviewed_at", "TIMESTAMP WITH TIME ZONE"),
    ("audit_events", "source_type", "VARCHAR(50)"),
    ("audit_events", "source_id", "UUID"),
)


async def _ensure_audit_event_enum_values(connection) -> None:
    for value in _ADDITIONAL_AUDIT_EVENT_VALUES:
        await connection.execute(
            text(
                "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
                f"'{value}'"
            )
        )


async def _ensure_task7_columns(connection) -> None:
    for table, column, type_sql in _TASK7_COLUMNS:
        await connection.execute(
            text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                f"{column} {type_sql}"
            )
        )


async def _ensure_audit_event_sequence_index(connection) -> None:
    index_exists = await connection.execute(
        text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE tablename = 'audit_events'
              AND indexname = 'uq_audit_event_scope_sequence'
            """
        )
    )
    if (
        index_exists is not None
        and index_exists.scalar_one_or_none() is not None
    ):
        return

    await connection.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY batch_id
                           ORDER BY sequence, occurred_at, id
                       ) AS next_sequence
                FROM audit_events
            )
            UPDATE audit_events AS event
            SET sequence = -(ranked.next_sequence::integer)
            FROM ranked
            WHERE event.id = ranked.id
            """
        )
    )
    await connection.execute(text("UPDATE audit_events SET sequence = -sequence"))
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_event_scope_sequence "
            "ON audit_events ((COALESCE(batch_id::text, '__global__')), sequence)"
        )
    )


async def initialize_database() -> None:
    """Create or upgrade the local schema before the API starts serving."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_audit_event_enum_values(connection)
        await _ensure_task7_columns(connection)
        await _ensure_audit_event_sequence_index(connection)


async def _run_initialization() -> None:
    try:
        await initialize_database()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_initialization())
