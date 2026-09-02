from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ask.router import router as ask_router
from app.ai.model import AIInvestigationRecord  # noqa: F401
from app.audit.model import AuditEvent  # noqa: F401
from app.bank.model import BankTransferPayment  # noqa: F401
from app.bank.router import router as bank_router
from app.batch.model import Batch, IngestionRecord  # noqa: F401
from app.batch.router import router as batch_router
from app.common.base import Base
from app.common.code_sequence import CodeSequence  # noqa: F401
from app.currency.model import Currency  # noqa: F401
from app.database import engine
from app.demo.router import router as demo_router
from app.evaluation.model import EvaluationCase, GroundTruthLink  # noqa: F401
from app.ledger.model import LedgerEntry  # noqa: F401
from app.ledger.router import router as ledger_router
from app.merchant.model import Merchant  # noqa: F401
from app.payment.model import Payment  # noqa: F401
from app.payment.router import router as payment_router
from app.paypal.model import PaypalPayment  # noqa: F401
from app.paypal.router import router as paypal_router
from app.provider.model import Provider  # noqa: F401
from app.razorpay.model import (  # noqa: F401
    RazorpayOrder,
    RazorpayPayment,
    RazorpayRefund,
)
from app.razorpay.router import router as razorpay_router
from app.reconciliation.model import (  # noqa: F401
    MatchLink,
    ReconciliationException,
    ReconciliationResult,
    ReconciliationRun,
)
from app.reconciliation.router import (
    metrics_router,
)
from app.reconciliation.router import (
    router as reconciliation_router,
)
from app.seed.router import router as seed_router
from app.settlement.model import BankCredit, Settlement, SettlementLine  # noqa: F401
from app.stripe.model import StripePayment  # noqa: F401
from app.stripe.router import router as stripe_router

_RAZORPAY_AUDIT_EVENT_VALUES = (
    "razorpay_sync_started",
    "razorpay_sync_completed",
    "razorpay_sync_failed",
)


async def _ensure_audit_event_enum_values(connection) -> None:
    for value in _RAZORPAY_AUDIT_EVENT_VALUES:
        await connection.execute(
            text(
                "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS "
                f"'{value}'"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and test connection
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_audit_event_enum_values(conn)
    print("Database tables created")
    yield
    # Shutdown: close all connections
    await engine.dispose()


app = FastAPI(
    title="Payment Reconciliation API",
    description="Reconciliation dashboard for matching internal payments with provider records",
    version="0.1.0",
    lifespan=lifespan,
)

from app.config import settings as app_settings  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(seed_router)
app.include_router(payment_router)
app.include_router(stripe_router)
app.include_router(paypal_router)
app.include_router(bank_router)
app.include_router(batch_router)
app.include_router(demo_router)
app.include_router(razorpay_router)
app.include_router(ledger_router)
app.include_router(reconciliation_router)
app.include_router(metrics_router)
app.include_router(ask_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
