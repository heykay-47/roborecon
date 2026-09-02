import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "razorpay"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_http_source_uses_basic_auth_bounded_get_pagination_and_canonical_mapping():
    from app.razorpay.adapter import HttpRazorpaySource

    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Basic a2V5LWlkOnNlY3JldA=="
        skip = request.url.params.get("skip", "0")
        if request.url.path == "/v1/orders":
            payload = fixture("orders-page-1.json") if skip == "0" else fixture(
                "orders-page-2.json"
            ) if skip == "1" else {"entity": "collection", "count": 0, "items": []}
        elif request.url.path == "/v1/payments":
            payload = fixture("payments.json") if skip == "0" else {
                "entity": "collection", "count": 0, "items": []
            }
        elif request.url.path == "/v1/refunds":
            payload = fixture("refunds.json") if skip == "0" else {
                "entity": "collection", "count": 0, "items": []
            }
        elif request.url.path == "/v1/settlements":
            payload = fixture("settlements.json") if skip == "0" else {
                "entity": "collection", "count": 0, "items": []
            }
        elif request.url.path == "/v1/settlements/recon/combined":
            payload = fixture("settlement-recon.json") if skip == "0" else {
                "entity": "collection", "count": 0, "items": []
            }
        else:
            raise AssertionError(f"unexpected path: {request.url.path}")
        return httpx.Response(200, json=payload)

    source = HttpRazorpaySource(
        key_id="key-id",
        key_secret="secret",
        base_url="https://razorpay.test",
        page_size=1,
        max_pages=4,
        transport=httpx.MockTransport(handler),
    )

    snapshot = await source.fetch_snapshot()

    assert [row.provider_order_id for row in snapshot.razorpay_orders] == [
        "order_demo_001",
        "order_demo_002",
    ]
    assert snapshot.razorpay_orders[0].receipt == "RCPT-0001"
    assert snapshot.razorpay_payments[0].provider_payment_id == "pay_demo_001"
    assert snapshot.razorpay_payments[0].provider_order_id == "order_demo_001"
    assert snapshot.razorpay_payments[0].receipt == "RCPT-0001"
    assert snapshot.razorpay_refunds[0].provider_refund_id == "rfnd_demo_001"
    assert snapshot.razorpay_refunds[0].provider_payment_id == "pay_demo_001"
    assert snapshot.settlements[0].provider_settlement_id == "setl_demo_001"
    assert snapshot.settlements[0].fee == 2500
    assert snapshot.settlements[0].tax == 500
    assert snapshot.settlements[0].utr == "UTR-DEMO-001"
    assert snapshot.source_row_count == 5
    assert snapshot.bank_credits == ()
    assert {request.method for request in requests} == {"GET"}
    assert all(request.url.params.get("count") == "1" for request in requests)


def test_http_source_uses_order_id_when_razorpay_receipt_is_null():
    from app.razorpay.adapter import HttpRazorpaySource

    snapshot = HttpRazorpaySource._map_snapshot(
        [
            {
                "id": "order_without_receipt",
                "amount": 100,
                "currency": "INR",
                "receipt": None,
                "status": "created",
                "created_at": 1754000000,
            }
        ],
        [],
        [],
        [],
        [],
    )

    assert snapshot.razorpay_orders[0].receipt == "order_without_receipt"


@pytest.mark.asyncio
async def test_http_source_rejects_invalid_collection_without_mutating_anything():
    from app.razorpay.adapter import HttpRazorpaySource, RazorpayAdapterError

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"entity": "collection", "items": "bad"})

    source = HttpRazorpaySource(
        key_id="key-id",
        key_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RazorpayAdapterError):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_http_source_rejects_silent_truncation_at_max_pages():
    from app.razorpay.adapter import HttpRazorpaySource, RazorpayAdapterError

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/orders":
            return httpx.Response(200, json={"entity": "collection", "count": 0, "items": []})
        return httpx.Response(
            200,
            json={
                "entity": "collection",
                "count": 1,
                "items": [
                    {
                        "id": "order_full_page",
                        "amount": 100,
                        "currency": "INR",
                        "receipt": "RCPT-FULL",
                        "status": "paid",
                        "created_at": 1754000000,
                    }
                ],
            },
        )

    source = HttpRazorpaySource(
        key_id="key-id",
        key_secret="secret",
        page_size=1,
        max_pages=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RazorpayAdapterError, match="pagination limit"):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_http_source_rejects_missing_provider_linkage_and_timestamp():
    from app.razorpay.adapter import HttpRazorpaySource, RazorpayAdapterError

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/orders":
            return httpx.Response(200, json={"entity": "collection", "count": 0, "items": []})
        if request.url.path == "/v1/payments":
            return httpx.Response(
                200,
                json={
                    "entity": "collection",
                    "count": 1,
                    "items": [
                        {
                            "id": "pay_missing_order",
                            "amount": 100,
                            "currency": "INR",
                            "status": "captured",
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"entity": "collection", "count": 0, "items": []})

    source = HttpRazorpaySource(
        key_id="key-id",
        key_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RazorpayAdapterError, match="mapping failed"):
        await source.fetch_snapshot()


def test_http_source_rejects_unknown_status_and_settlement_type():
    from app.razorpay.adapter import HttpRazorpaySource, RazorpayAdapterError

    with pytest.raises(RazorpayAdapterError, match="mapping failed"):
        HttpRazorpaySource._map_snapshot(
            [],
            [
                {
                    "id": "pay_unknown_status",
                    "order_id": "order_1",
                    "amount": 100,
                    "currency": "INR",
                    "status": "unknown",
                    "captured": False,
                    "created_at": 1754000000,
                }
            ],
            [],
            [],
            [],
        )

    with pytest.raises(RazorpayAdapterError, match="mapping failed"):
        HttpRazorpaySource._map_snapshot(
            [],
            [],
            [],
            [
                {
                    "id": "setl_1",
                    "amount": 100,
                    "currency": "INR",
                    "status": "processed",
                    "fees": 0,
                    "tax": 0,
                    "utr": "UTR-1",
                    "created_at": 1754000000,
                }
            ],
            [
                {
                    "entity_id": "pay_1",
                    "type": "unknown",
                    "amount": 100,
                    "currency": "INR",
                    "settlement_id": "setl_1",
                    "created_at": 1754000000,
                }
            ],
        )


@pytest.mark.asyncio
async def test_http_source_rejects_settlement_without_utr_and_never_fabricates_bank_credit():
    from app.razorpay.adapter import HttpRazorpaySource, RazorpayAdapterError

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settlements":
            return httpx.Response(
                200,
                json={
                    "entity": "collection",
                    "count": 1,
                    "items": [
                        {
                            "id": "setl_without_utr",
                            "amount": 100,
                            "currency": "INR",
                            "status": "processed",
                            "fees": 0,
                            "tax": 0,
                            "created_at": 1754000000,
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"entity": "collection", "count": 0, "items": []})

    source = HttpRazorpaySource(
        key_id="key-id",
        key_secret="secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RazorpayAdapterError, match="mapping failed"):
        await source.fetch_snapshot()


@pytest.mark.asyncio
async def test_demo_source_is_a_fixed_connector_snapshot_not_the_hidden_benchmark():
    from app.razorpay.adapter import DemoRazorpaySource

    snapshot = await DemoRazorpaySource().fetch_snapshot()

    assert snapshot.source_row_count > 0
    assert len(snapshot.razorpay_orders) < 10
    assert snapshot.ledger_entries == ()
    assert snapshot.bank_credits == ()
    assert not hasattr(snapshot, "truth_cases")
    assert all(isinstance(row.id, UUID) for row in snapshot.razorpay_orders)


def test_source_selection_falls_back_when_either_key_is_absent(monkeypatch):
    from app.config import settings
    from app.razorpay import router
    from app.razorpay.adapter import DemoRazorpaySource, HttpRazorpaySource

    monkeypatch.setattr(settings, "razorpay_key_id", "key-id")
    monkeypatch.setattr(settings, "razorpay_key_secret", None)
    assert isinstance(router.source_from_settings(), DemoRazorpaySource)

    monkeypatch.setattr(settings, "razorpay_key_secret", "secret")
    assert isinstance(router.source_from_settings(), HttpRazorpaySource)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _AuditResult:
    def scalar_one_or_none(self):
        return SimpleNamespace()

    def scalar_one(self):
        return 0


class _Session:
    def __init__(self):
        self.added = []

    def begin(self):
        return _Transaction()

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    async def execute(self, _statement):
        return _AuditResult()

    async def flush(self):
        return None


class _FailingPersistenceSession(_Session):
    def add_all(self, values):
        raise RuntimeError("persistence failed")


@pytest.mark.asyncio
async def test_sync_persists_an_isolated_unscored_batch_and_audit_lifecycle():
    from app.common.enums import AuditEventType, BatchKind
    from app.razorpay.adapter import DemoRazorpaySource
    from app.razorpay.router import sync_snapshot

    session = _Session()
    batch, counts = await sync_snapshot(session, DemoRazorpaySource())

    assert batch.kind is BatchKind.test_mode_sync
    assert batch.ground_truth_available is False
    assert batch.source_row_count == counts["total"]
    events = [value for value in session.added if hasattr(value, "event_type")]
    assert [event.event_type for event in events] == [
        AuditEventType.razorpay_sync_started,
        AuditEventType.razorpay_sync_completed,
    ]
    assert not any(
        type(value).__name__ in {"EvaluationCase", "GroundTruthLink"}
        for value in session.added
    )


@pytest.mark.asyncio
async def test_failed_fetch_persists_failed_batch_audit_event():
    from fastapi import HTTPException

    from app.common.enums import AuditEventType, BatchStatus
    from app.razorpay.adapter import RazorpayAdapterError
    from app.razorpay.router import sync_snapshot

    class FailingSource:
        async def fetch_snapshot(self):
            raise RazorpayAdapterError("provider unavailable")

    session = _Session()

    with pytest.raises(HTTPException) as error:
        await sync_snapshot(session, FailingSource())

    assert error.value.status_code == 502
    batch = session.added[0]
    assert batch.status is BatchStatus.failed
    assert [event.event_type for event in session.added[1:]] == [
        AuditEventType.razorpay_sync_started,
        AuditEventType.razorpay_sync_failed,
    ]


@pytest.mark.asyncio
async def test_failed_persistence_persists_failed_audit_event():
    from fastapi import HTTPException

    from app.common.enums import AuditEventType, BatchStatus
    from app.razorpay.adapter import DemoRazorpaySource
    from app.razorpay.router import sync_snapshot

    session = _FailingPersistenceSession()

    with pytest.raises(HTTPException) as error:
        await sync_snapshot(session, DemoRazorpaySource())

    assert error.value.status_code == 502
    batch = session.added[0]
    assert batch.status is BatchStatus.failed
    assert [event.event_type for event in session.added[1:]] == [
        AuditEventType.razorpay_sync_started,
        AuditEventType.razorpay_sync_failed,
    ]


@pytest.mark.asyncio
async def test_sync_endpoint_returns_a_test_mode_batch(client, monkeypatch):
    from app.config import settings
    from app.database import get_session
    from app.main import app

    monkeypatch.setattr(settings, "razorpay_key_id", None)
    monkeypatch.setattr(settings, "razorpay_key_secret", None)
    session = _Session()
    app.dependency_overrides[get_session] = lambda: session

    response = await client.post("/razorpay/sync")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "test_mode_sync"
    assert payload["groundTruthAvailable"] is False
    assert payload["sourceCounts"]["total"] > 0


@pytest.mark.asyncio
async def test_failed_sync_persists_a_failed_batch(client, monkeypatch):
    from app.database import get_session
    from app.main import app
    from app.razorpay import router
    from app.razorpay.adapter import RazorpayAdapterError

    class FailingSource:
        async def fetch_snapshot(self):
            raise RazorpayAdapterError("provider unavailable")

    session = _Session()
    app.dependency_overrides[get_session] = lambda: session
    monkeypatch.setattr(router, "source_from_settings", lambda: FailingSource())

    response = await client.post("/razorpay/sync")

    assert response.status_code == 502
    assert session.added[0].status.value == "failed"
    assert session.added[-1].event_type.value == "razorpay.sync.failed"


@pytest.mark.asyncio
async def test_existing_audit_enum_values_are_migrated():
    from app.main import _ensure_audit_event_enum_values

    class Connection:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(str(statement))

    connection = Connection()
    await _ensure_audit_event_enum_values(connection)

    assert len(connection.statements) == 3
    assert all(
        statement.startswith(
            "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS"
        )
        for statement in connection.statements
    )
    assert all(
        value in statement
        for statement, value in zip(
            connection.statements,
            (
                "razorpay_sync_started",
                "razorpay_sync_completed",
                "razorpay_sync_failed",
            ),
        )
    )
