import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError


@pytest.fixture
async def read_benchmark_workspace():
    from app.batch.model import Batch
    from app.common.enums import BatchKind, BatchStatus, LedgerEntryType
    from app.database import async_session, engine
    from app.database_init import initialize_database
    from app.demo.dataset import build_demo_dataset
    from app.demo.service import ROBORECON_TABLES, reset_demo
    from app.ledger.model import LedgerEntry

    try:
        await initialize_database()
    except (DBAPIError, OSError) as error:
        pytest.skip(f"PostgreSQL integration container is unavailable: {error}")

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    extra_batches = [
        Batch(
            id=uuid4(),
            kind=BatchKind.test_mode_sync,
            status=BatchStatus.completed,
            seed=f"read-benchmark-{index}",
            ground_truth_available=False,
            source_row_count=250,
            started_at=now,
            completed_at=now,
        )
        for index in range(2)
    ]

    fixed_dataset = build_demo_dataset()
    fixed_source_record_count = sum(
        len(records)
        for records in (
            fixed_dataset.ledger_entries,
            fixed_dataset.razorpay_orders,
            fixed_dataset.razorpay_payments,
            fixed_dataset.razorpay_refunds,
            fixed_dataset.settlements,
            fixed_dataset.settlement_lines,
            fixed_dataset.bank_credits,
            fixed_dataset.malformed_rows,
        )
    )

    async with async_session() as session:
        fixed_batch = await reset_demo(session)
        session.add_all(extra_batches)
        await session.flush()
        session.add_all(
            [
                LedgerEntry(
                    id=uuid4(),
                    batch_id=batch.id,
                    reference=f"BENCH-{batch_index}-{row_index:03d}",
                    entry_type=LedgerEntryType.payment,
                    amount=1_000 + row_index,
                    currency="INR",
                    business_at=now + timedelta(seconds=row_index),
                )
                for batch_index, batch in enumerate(extra_batches)
                for row_index in range(250)
            ]
        )
        await session.commit()

    try:
        from app.database import get_session
        from app.main import app

        async def real_session():
            async with async_session() as session:
                yield session

        app.dependency_overrides[get_session] = real_session
        yield fixed_batch.id, fixed_source_record_count
    finally:
        app.dependency_overrides.pop(get_session, None)
        async with async_session() as session:
            async with session.begin():
                for model in ROBORECON_TABLES:
                    await session.execute(delete(model))
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_paths_record_fixed_and_multiple_batch_timings(
    read_benchmark_workspace,
):
    from app.main import app

    fixed_batch_id, fixed_source_record_count = read_benchmark_workspace
    endpoints = (
        "/batches?page=1&page_size=50",
        "/reconciliation-runs?page=1&page_size=50",
        "/transactions?page=1&page_size=50",
        f"/transactions?batch_id={fixed_batch_id}&page=1&page_size=50",
        "/exceptions?page=1&page_size=50",
        "/audit-events?page=1&page_size=50",
    )
    timing_pattern = re.compile(
        r"db;dur=(?P<db>\d+\.\d{2}), "
        r"handler;dur=(?P<handler>\d+\.\d{2}), "
        r"total;dur=(?P<total>\d+\.\d{2})"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for endpoint in endpoints:
            response = await client.get(endpoint)
            assert response.status_code == 200
            if endpoint.startswith("/batches"):
                assert response.json()["total"] == 3
            if endpoint == "/transactions?page=1&page_size=50":
                assert response.json()["total"] == fixed_source_record_count + 500
            if endpoint.startswith(f"/transactions?batch_id={fixed_batch_id}"):
                assert response.json()["total"] == fixed_source_record_count
            assert response.headers.get("server-timing")
            for _ in range(5):
                response = await client.get(endpoint)
                assert response.status_code == 200
                timing = response.headers.get("server-timing", "")
                match = timing_pattern.fullmatch(timing)
                assert match is not None
                print(f"{endpoint} {timing}")
