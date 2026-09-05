from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import app.database_init  # noqa: F401
from app.audit.router import router as audit_router
from app.batch.router import router as batch_router
from app.common.timing import ReadTiming, current_read_timing
from app.config import settings as app_settings
from app.copilot.router import router as copilot_router
from app.database import engine
from app.demo.router import router as demo_router
from app.exception.router import router as exception_router
from app.ledger.router import router as ledger_router
from app.razorpay.router import router as razorpay_router
from app.reconciliation.router import (
    metrics_router,
)
from app.reconciliation.router import (
    router as reconciliation_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Payment Reconciliation API",
    description="Reconciliation dashboard for matching internal payments with provider records",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in app_settings.cors_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)

_TIMED_READ_PATHS = frozenset(
    {"/batches", "/transactions", "/reconciliation-runs", "/exceptions", "/audit-events"}
)


@app.middleware("http")
async def add_read_timing(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if request.method != "GET" or path not in _TIMED_READ_PATHS:
        return await call_next(request)

    timing = ReadTiming()
    token = current_read_timing.set(timing)
    started = perf_counter()
    try:
        response = await call_next(request)
        total_ms = (perf_counter() - started) * 1000
        handler_ms = max(total_ms - timing.database_ms, 0.0)
        response.headers["Server-Timing"] = (
            f"db;dur={timing.database_ms:.2f}, "
            f"handler;dur={handler_ms:.2f}, "
            f"total;dur={total_ms:.2f}"
        )
        return response
    finally:
        current_read_timing.reset(token)

app.include_router(batch_router)
app.include_router(demo_router)
app.include_router(razorpay_router)
app.include_router(ledger_router)
app.include_router(reconciliation_router)
app.include_router(metrics_router)
app.include_router(exception_router)
app.include_router(audit_router)
app.include_router(copilot_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
