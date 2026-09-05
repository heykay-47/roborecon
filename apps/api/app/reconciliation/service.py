from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter_ns
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit_service
from app.batch.model import Batch, IngestionRecord
from app.common.enums import (
    AuditEventType,
    ExceptionStatus,
    ReconciliationStage,
    ResultStatus,
    RunStatus,
)
from app.common.messages import MALFORMED_RECORD_MESSAGE
from app.config import settings
from app.database import async_session
from app.demo.dataset import (
    BankCreditSeed,
    LedgerEntrySeed,
    RazorpayOrderSeed,
    RazorpayPaymentSeed,
    RazorpayRefundSeed,
    SettlementLineSeed,
    SettlementSeed,
)
from app.ledger.model import LedgerEntry
from app.razorpay.model import RazorpayOrder, RazorpayPayment, RazorpayRefund
from app.reconciliation.engine import reconcile_stage_a, reconcile_stage_b
from app.reconciliation.model import (
    EngineOutcome,
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.settlement.model import BankCredit, Settlement, SettlementLine


class RunAlreadyRunning(RuntimeError):
    """Raised when a batch already has an active deterministic run."""


_EXCEPTION_MESSAGES: dict[ResultStatus, str] = {
    ResultStatus.matched: "A possible match was found, but it needs review.",
    ResultStatus.ambiguous: "More than one possible match was found. Review the evidence.",
    ResultStatus.duplicate: "More than one source record matched. Review the evidence.",
    ResultStatus.missing_razorpay: "No matching Razorpay record was found.",
    ResultStatus.missing_ledger: "No matching ledger record was found.",
    ResultStatus.missing_settlement: "No matching settlement was found.",
    ResultStatus.missing_bank_credit: "No matching bank credit was found.",
    ResultStatus.amount_mismatch: "The amounts do not match. Review the evidence.",
    ResultStatus.malformed: MALFORMED_RECORD_MESSAGE,
    ResultStatus.confirmed_no_match: "No match was confirmed. Review the evidence.",
}


def _exception_message(status: ResultStatus) -> str:
    return _EXCEPTION_MESSAGES.get(status, "This result needs review. Check the evidence.")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _source_counts(
    ledger: list[LedgerEntry],
    orders: list[RazorpayOrder],
    payments: list[RazorpayPayment],
    refunds: list[RazorpayRefund],
    settlements: list[Settlement],
    credits: list[BankCredit],
    quarantine: list[IngestionRecord],
) -> dict[str, int]:
    counts = {
        "ledger": len(ledger),
        "razorpayOrders": len(orders),
        "razorpayPayments": len(payments),
        "razorpayRefunds": len(refunds),
        "settlements": len(settlements),
        "bankCredits": len(credits),
        "quarantined": len(quarantine),
    }
    counts["total"] = sum(counts.values())
    return counts


async def _load_snapshot(
    session: AsyncSession,
    batch_id: UUID,
) -> tuple[Batch, dict[str, list[Any]], dict[str, int]]:
    batch = await session.get(Batch, batch_id)
    if batch is None:
        raise ValueError("Reconciliation batch was not found")

    async def load(model: Any) -> list[Any]:
        result = await session.execute(
            select(model).where(model.batch_id == batch_id).order_by(model.id)
        )
        return list(result.scalars().all())

    source_rows = {
        "ledger": await load(LedgerEntry),
        "orders": await load(RazorpayOrder),
        "payments": await load(RazorpayPayment),
        "refunds": await load(RazorpayRefund),
        "settlements": await load(Settlement),
        "lines": await load(SettlementLine),
        "credits": await load(BankCredit),
        "quarantine": await load(IngestionRecord),
    }
    counts = _source_counts(
        source_rows["ledger"],
        source_rows["orders"],
        source_rows["payments"],
        source_rows["refunds"],
        source_rows["settlements"],
        source_rows["credits"],
        source_rows["quarantine"],
    )
    return batch, source_rows, counts


def _seed_sources(source_rows: dict[str, list[Any]]) -> dict[str, list[Any]]:
    return {
        "ledger": [
            LedgerEntrySeed(
                id=row.id,
                reference=row.reference,
                entry_type=row.entry_type,
                amount=row.amount,
                currency=row.currency,
                business_at=row.business_at,
            )
            for row in source_rows["ledger"]
        ],
        "orders": [
            RazorpayOrderSeed(
                id=row.id,
                provider_order_id=row.provider_order_id,
                receipt=row.receipt,
                amount=row.amount,
                currency=row.currency,
                status=row.status,
                business_at=row.business_at,
            )
            for row in source_rows["orders"]
        ],
        "payments": [
            RazorpayPaymentSeed(
                id=row.id,
                provider_payment_id=row.provider_payment_id,
                provider_order_id=row.provider_order_id,
                receipt=row.receipt,
                amount=row.amount,
                currency=row.currency,
                status=row.status,
                captured=row.captured,
                business_at=row.business_at,
            )
            for row in source_rows["payments"]
        ],
        "refunds": [
            RazorpayRefundSeed(
                id=row.id,
                provider_refund_id=row.provider_refund_id,
                provider_payment_id=row.provider_payment_id,
                amount=row.amount,
                currency=row.currency,
                status=row.status,
                business_at=row.business_at,
            )
            for row in source_rows["refunds"]
        ],
        "settlements": [
            SettlementSeed(
                id=row.id,
                provider_settlement_id=row.provider_settlement_id,
                amount=row.amount,
                fee=row.fee,
                tax=row.tax,
                held_amount=row.held_amount,
                currency=row.currency,
                utr=row.utr,
                status=row.status,
                business_at=row.business_at,
            )
            for row in source_rows["settlements"]
        ],
        "lines": [
            SettlementLineSeed(
                id=row.id,
                settlement_id=row.settlement_id,
                line_type=row.line_type,
                reference=row.reference,
                amount=row.amount,
                currency=row.currency,
                business_at=row.business_at,
            )
            for row in source_rows["lines"]
        ],
        "credits": [
            BankCreditSeed(
                id=row.id,
                settlement_id=row.settlement_id,
                utr=row.utr,
                amount=row.amount,
                currency=row.currency,
                business_at=row.business_at,
            )
            for row in source_rows["credits"]
        ],
    }


def _source_index(source_rows: dict[str, list[Any]]) -> dict[str, tuple[str, Any]]:
    index: dict[str, tuple[str, Any]] = {}
    for source_type, rows in (
        ("ledger", source_rows["ledger"]),
        ("razorpay_order", source_rows["orders"]),
        ("razorpay_payment", source_rows["payments"]),
        ("razorpay_refund", source_rows["refunds"]),
        ("settlement", source_rows["settlements"]),
        ("settlement_line", source_rows["lines"]),
        ("bank_credit", source_rows["credits"]),
    ):
        index.update({str(row.id): (source_type, row) for row in rows})
    return index


def _outcome_result(
    *,
    run: ReconciliationRun,
    batch_id: UUID,
    outcome: EngineOutcome,
    primary_source_type: str,
    primary_source_id: UUID | None,
    amount: int | None,
    currency: str | None,
) -> ReconciliationResult:
    return ReconciliationResult(
        id=uuid4(),
        run_id=run.id,
        batch_id=batch_id,
        stage=outcome.stage,
        status=outcome.status,
        primary_source_type=primary_source_type,
        primary_source_id=primary_source_id,
        amount=amount,
        currency=currency,
        score=outcome.score,
        runner_up_score=outcome.runner_up_score,
        margin=outcome.margin,
        autonomous=outcome.autonomous,
        selected_ids=_jsonable(outcome.selected_ids),
        evidence=_jsonable(outcome.evidence),
        candidates=_jsonable(outcome.candidates),
    )


def _add_links_and_exception(
    session: AsyncSession,
    *,
    run: ReconciliationRun,
    result: ReconciliationResult,
    outcome: EngineOutcome,
    source_index: dict[str, tuple[str, Any]],
    batch_id: UUID,
) -> None:
    links: list[tuple[str, UUID, str]] = []
    if result.primary_source_id is not None:
        links.append((result.primary_source_type, result.primary_source_id, "primary"))
    for selected_id in outcome.selected_ids:
        source = source_index.get(str(selected_id))
        if source is not None:
            links.append((source[0], source[1].id, "selected"))

    def add_related_order(source: tuple[str, Any]) -> None:
        source_type, source_row = source
        provider_order_id: str | None = None
        if source_type == "razorpay_payment":
            provider_order_id = source_row.provider_order_id
        elif source_type == "razorpay_refund":
            parent_payment = next(
                (
                    row
                    for row_type, row in source_index.values()
                    if row_type == "razorpay_payment"
                    and row.provider_payment_id == source_row.provider_payment_id
                ),
                None,
            )
            provider_order_id = (
                parent_payment.provider_order_id if parent_payment is not None else None
            )
        if provider_order_id is None:
            return
        order = next(
            (
                row
                for row_type, row in source_index.values()
                if row_type == "razorpay_order"
                and row.provider_order_id == provider_order_id
            ),
            None,
        )
        if order is not None:
            links.append(("razorpay_order", order.id, "related"))

    if result.stage is ReconciliationStage.ledger_to_razorpay:
        if result.primary_source_id is not None:
            primary_source = source_index.get(str(result.primary_source_id))
            if primary_source is not None:
                add_related_order(primary_source)
        for selected_id in outcome.selected_ids:
            selected_source = source_index.get(str(selected_id))
            if selected_source is not None:
                add_related_order(selected_source)
    seen: set[tuple[str, UUID]] = set()
    for source_type, source_id, role in links:
        key = (source_type, source_id)
        if key in seen:
            continue
        seen.add(key)
        session.add(
            MatchLink(
                run_id=run.id,
                result_id=result.id,
                source_type=source_type,
                source_id=source_id,
                role=role,
                autonomous=outcome.autonomous,
                actor="system",
            )
        )
    if not outcome.autonomous:
        session.add(
            ReconciliationException(
                run_id=run.id,
                result_id=result.id,
                batch_id=batch_id,
                status=ExceptionStatus.open,
                exception_type=outcome.status.value,
                source_type=result.primary_source_type,
                source_id=result.primary_source_id,
                amount=result.amount,
                message=_exception_message(outcome.status),
            )
        )


async def _audit(
    session: AsyncSession,
    *,
    batch_id: UUID,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: UUID | None,
    summary: str,
) -> None:
    await audit_service.append_event(
        session,
        batch_id=batch_id,
        event_type=event_type,
        actor="system",
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
    )


async def run_reconciliation(
    session: AsyncSession,
    batch_id: UUID,
    *,
    investigate: bool = True,
) -> ReconciliationRun:
    """Run both pure deterministic stages against one fixed batch snapshot."""
    started_at = datetime.now(timezone.utc)
    started_ticks = perf_counter_ns()
    try:
        if await session.get(Batch, batch_id) is None:
            raise ValueError("Reconciliation batch was not found")
        running = (
            await session.execute(
                select(ReconciliationRun).where(
                    ReconciliationRun.batch_id == batch_id,
                    ReconciliationRun.status == RunStatus.running,
                )
            )
        ).scalar_one_or_none()
        if running is not None:
            raise RunAlreadyRunning(
                "A reconciliation run is already running for this batch"
            )
        await session.rollback()
        async with session.begin():
            await session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
            run = ReconciliationRun(
                batch_id=batch_id,
                status=RunStatus.running,
                started_at=started_at,
                source_row_count=0,
                source_counts={},
            )
            session.add(run)
            try:
                await session.flush()
            except IntegrityError as error:
                raise RunAlreadyRunning(
                    "A reconciliation run is already running for this batch"
                ) from error
            await _audit(
                session,
                batch_id=batch_id,
                event_type=AuditEventType.run_started,
                entity_type="reconciliation_run",
                entity_id=run.id,
                summary="Reconciliation run started",
            )
            batch, source_rows, source_counts = await _load_snapshot(session, batch_id)
            seeds = _seed_sources(source_rows)
            source_index = _source_index(source_rows)
            stage_a_outcomes = reconcile_stage_a(
                seeds["ledger"],
                seeds["orders"],
                seeds["payments"],
                seeds["refunds"],
            )
            stage_b_outcomes = reconcile_stage_b(
                seeds["payments"],
                seeds["refunds"],
                seeds["settlements"],
                seeds["lines"],
                seeds["credits"],
            )

            ledger_rows = source_rows["ledger"]
            pending_outcomes: list[tuple[ReconciliationResult, EngineOutcome]] = []
            for index, outcome in enumerate(stage_a_outcomes):
                if index < len(ledger_rows):
                    primary = ledger_rows[index]
                    primary_type = "ledger"
                else:
                    selected = next(iter(outcome.selected_ids), None)
                    source = source_index.get(str(selected)) if selected else None
                    primary_type = source[0] if source else "source"
                    primary = source[1] if source else None
                result = _outcome_result(
                    run=run,
                    batch_id=batch.id,
                    outcome=outcome,
                    primary_source_type=primary_type,
                    primary_source_id=primary.id if primary is not None else None,
                    amount=primary.amount if primary is not None else None,
                    currency=primary.currency if primary is not None else None,
                )
                session.add(result)
                pending_outcomes.append((result, outcome))

            captured_payments = [
                row
                for row in source_rows["payments"]
                if row.captured and _jsonable(row.status) == "captured"
            ]
            for payment, outcome in zip(captured_payments, stage_b_outcomes):
                result = _outcome_result(
                    run=run,
                    batch_id=batch.id,
                    outcome=outcome,
                    primary_source_type="razorpay_payment",
                    primary_source_id=payment.id,
                    amount=payment.amount,
                    currency=payment.currency,
                )
                session.add(result)
                pending_outcomes.append((result, outcome))

            # Results must exist before their separately persisted links can be flushed.
            await session.flush()
            for result, outcome in pending_outcomes:
                _add_links_and_exception(
                    session,
                    run=run,
                    result=result,
                    outcome=outcome,
                    source_index=source_index,
                    batch_id=batch.id,
                )

            for row in source_rows["quarantine"]:
                session.add(
                    ReconciliationException(
                        run_id=run.id,
                        result_id=None,
                        batch_id=batch.id,
                        status=ExceptionStatus.open,
                        exception_type="malformed",
                        source_type="quarantine",
                        source_id=None,
                        amount=None,
                         message=_exception_message(ResultStatus.malformed),
                    )
                )

            elapsed_ms = max(0, round((perf_counter_ns() - started_ticks) / 1_000_000))
            run.status = RunStatus.completed
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = elapsed_ms
            run.source_counts = source_counts
            run.source_row_count = source_counts["total"]
            run.throughput = (
                round(source_counts["total"] / (elapsed_ms / 1_000), 2)
                if elapsed_ms
                else 0.0
            )
            await _audit(
                session,
                batch_id=batch.id,
                event_type=AuditEventType.result_persisted,
                entity_type="reconciliation_run",
                entity_id=run.id,
                summary="Deterministic reconciliation results persisted",
            )
            await _audit(
                session,
                batch_id=batch.id,
                event_type=AuditEventType.run_completed,
                entity_type="reconciliation_run",
                entity_id=run.id,
                summary="Reconciliation run completed",
            )
        # Serverless requests must return before external advisory provider I/O.
        if investigate and not settings.serverless:
            await _investigate_after_commit(session, run)
        return run
    except (RunAlreadyRunning, ValueError):
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        elapsed_ms = max(0, round((perf_counter_ns() - started_ticks) / 1_000_000))
        failed_run = ReconciliationRun(
            batch_id=batch_id,
            status=RunStatus.failed,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            duration_ms=elapsed_ms,
            source_row_count=0,
            source_counts={},
            error_message="Reconciliation failed before completion.",
        )
        try:
            session.add(failed_run)
            await session.flush()
            await _audit(
                session,
                batch_id=batch_id,
                event_type=AuditEventType.run_failed,
                entity_type="reconciliation_run",
                entity_id=failed_run.id,
                summary="Reconciliation run failed",
            )
            await session.commit()
        except Exception:
            await session.rollback()
        raise


async def _investigate_after_commit(
    session: AsyncSession,
    run: ReconciliationRun,
) -> None:
    """Run the bounded advisory portfolio without changing deterministic outcomes."""
    if run.id is None:
        return
    try:
        from app.ai.investigator import investigate_completed_run

        async with async_session() as ai_session:
            try:
                await investigate_completed_run(ai_session, run.id)
            except Exception:
                await ai_session.rollback()
    except Exception:
        # Provider, tool, or isolated AI-session failures are fail-safe.
        return
