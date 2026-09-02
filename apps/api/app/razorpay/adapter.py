from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
)

from app.common.enums import RazorpayPaymentStatus, SettlementLineType

MAX_PAGE_SIZE = 100
MAX_PAGES = 50
MAX_TIMEOUT_SECONDS = 60.0


class RazorpayAdapterError(RuntimeError):
    """Raised when a read-only Razorpay response cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class OrderRecord:
    id: UUID
    provider_order_id: str
    receipt: str
    amount: int
    currency: str
    status: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    id: UUID
    provider_payment_id: str
    provider_order_id: str
    receipt: str
    amount: int
    currency: str
    status: RazorpayPaymentStatus
    captured: bool
    business_at: datetime


@dataclass(frozen=True, slots=True)
class RefundRecord:
    id: UUID
    provider_refund_id: str
    provider_payment_id: str
    amount: int
    currency: str
    status: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    id: UUID
    provider_settlement_id: str
    amount: int
    fee: int
    tax: int
    held_amount: int
    currency: str
    utr: str
    status: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementLineRecord:
    id: UUID
    settlement_id: UUID
    line_type: SettlementLineType
    reference: str
    amount: int
    currency: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class BankCreditRecord:
    id: UUID
    settlement_id: UUID
    utr: str
    amount: int
    currency: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class RazorpaySnapshot:
    ledger_entries: tuple = ()
    razorpay_orders: tuple[OrderRecord, ...] = ()
    razorpay_payments: tuple[PaymentRecord, ...] = ()
    razorpay_refunds: tuple[RefundRecord, ...] = ()
    settlements: tuple[SettlementRecord, ...] = ()
    settlement_lines: tuple[SettlementLineRecord, ...] = ()
    bank_credits: tuple[BankCreditRecord, ...] = ()
    malformed_rows: tuple = ()

    @property
    def source_row_count(self) -> int:
        return sum(
            (
                len(self.ledger_entries),
                len(self.razorpay_orders),
                len(self.razorpay_payments),
                len(self.razorpay_refunds),
                len(self.settlements),
                len(self.bank_credits),
                len(self.malformed_rows),
            )
        )


class _Collection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity: Literal["collection"]
    count: StrictInt = Field(ge=0)
    items: list[dict[str, Any]]


class _OrderPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    amount: StrictInt = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    receipt: str = Field(min_length=1)
    status: Literal["created", "attempted", "paid"]
    created_at: StrictInt = Field(gt=0)


class _PaymentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    amount: StrictInt = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal[
        "created",
        "authorized",
        "captured",
        "failed",
        "refunded",
        "partially_refunded",
    ]
    captured: StrictBool | None = None
    created_at: StrictInt = Field(gt=0)


class _RefundPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    payment_id: str = Field(min_length=1)
    amount: StrictInt = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["pending", "processed", "failed"]
    created_at: StrictInt = Field(gt=0)


class _SettlementPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    amount: StrictInt = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal[
        "created",
        "initiated",
        "processed",
        "failed",
        "reversed",
        "partially_processed",
    ]
    fees: StrictInt = Field(
        validation_alias=AliasChoices("fees", "fee"), ge=0
    )
    tax: StrictInt = Field(ge=0)
    utr: str = Field(min_length=1)
    created_at: StrictInt = Field(gt=0)


class _ReconPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(min_length=1)
    type: Literal[
        "payment",
        "refund",
        "transfer",
        "fee",
        "tax",
        "hold",
        "release",
        "adjustment",
    ]
    debit: StrictInt = Field(ge=0)
    credit: StrictInt = Field(ge=0)
    amount: StrictInt = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    fee: StrictInt = Field(ge=0)
    tax: StrictInt = Field(ge=0)
    on_hold: StrictBool = False
    settled: StrictBool = False
    created_at: StrictInt = Field(gt=0)
    settled_at: StrictInt | None = Field(default=None, gt=0)
    settlement_id: str = Field(min_length=1)
    payment_id: str | None = None
    settlement_utr: str | None = None
    order_id: str | None = None
    order_receipt: str | None = None


class RazorpaySource:
    async def fetch_snapshot(self) -> RazorpaySnapshot:
        raise NotImplementedError


def _business_at(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _payment_status(status: str) -> RazorpayPaymentStatus:
    try:
        return RazorpayPaymentStatus(status)
    except ValueError as exc:
        raise RazorpayAdapterError(f"Unknown Razorpay payment status: {status}") from exc


def _line_type(value: str) -> SettlementLineType:
    try:
        return SettlementLineType(value)
    except ValueError as exc:
        raise RazorpayAdapterError(f"Unknown Razorpay settlement type: {value}") from exc


class HttpRazorpaySource(RazorpaySource):
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        base_url: str = "https://api.razorpay.com",
        page_size: int = 100,
        max_pages: int = 10,
        timeout: float = 10.0,
        settlement_recon_params: dict[str, int] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        self.max_pages = min(max(max_pages, 1), MAX_PAGES)
        self.timeout = min(max(timeout, 0.1), MAX_TIMEOUT_SECONDS)
        recon_date = datetime.now(timezone.utc)
        self.settlement_recon_params = settlement_recon_params or {
            "year": recon_date.year,
            "month": recon_date.month,
        }
        self._client = client
        self._transport = transport
        self._auth = httpx.BasicAuth(key_id, key_secret)
        self._base_url = base_url.rstrip("/")

    async def fetch_snapshot(self) -> RazorpaySnapshot:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            timeout=self.timeout,
            transport=self._transport,
        )
        if self._client is not None:
            client.auth = self._auth

        try:
            orders_raw = await self._fetch_collection(client, "/v1/orders")
            payments_raw = await self._fetch_collection(client, "/v1/payments")
            refunds_raw = await self._fetch_collection(client, "/v1/refunds")
            settlements_raw = await self._fetch_collection(client, "/v1/settlements")
            recon_raw = await self._fetch_collection(
                client,
                "/v1/settlement/recon/combined",
                initial_params=self.settlement_recon_params,
            )
            return self._map_snapshot(
                orders_raw, payments_raw, refunds_raw, settlements_raw, recon_raw
            )
        finally:
            if owns_client:
                await client.aclose()

    async def _fetch_collection(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        initial_params: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skip = 0
        for page_number in range(self.max_pages):
            params = dict(initial_params or {})
            params.update({"count": self.page_size, "skip": skip})
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
                collection = _Collection.model_validate(response.json())
            except (httpx.HTTPError, ValueError, ValidationError) as exc:
                raise RazorpayAdapterError(f"Invalid Razorpay response for {path}") from exc

            page_items = collection.items
            if collection.count != len(page_items):
                raise RazorpayAdapterError(
                    f"Invalid pagination count for {path}: "
                    f"count={collection.count}, items={len(page_items)}"
                )
            items.extend(page_items)
            if len(page_items) < self.page_size:
                break
            skip += len(page_items)
            if page_number == self.max_pages - 1:
                raise RazorpayAdapterError(
                    f"Razorpay pagination limit reached for {path}"
                )
        return items

    @staticmethod
    def _map_snapshot(
        orders_raw: list[dict[str, Any]],
        payments_raw: list[dict[str, Any]],
        refunds_raw: list[dict[str, Any]],
        settlements_raw: list[dict[str, Any]],
        recon_raw: list[dict[str, Any]],
    ) -> RazorpaySnapshot:
        try:
            orders_payload = [_OrderPayload.model_validate(row) for row in orders_raw]
            payments_payload = [
                _PaymentPayload.model_validate(row) for row in payments_raw
            ]
            refunds_payload = [_RefundPayload.model_validate(row) for row in refunds_raw]
            settlements_payload = [
                _SettlementPayload.model_validate(row) for row in settlements_raw
            ]
            recon_payload = [_ReconPayload.model_validate(row) for row in recon_raw]
        except ValidationError as exc:
            raise RazorpayAdapterError("Razorpay source mapping failed") from exc

        receipt_by_order = {
            payload.id: payload.receipt or payload.id for payload in orders_payload
        }
        orders = tuple(
            OrderRecord(
                id=uuid4(),
                provider_order_id=payload.id,
                receipt=payload.receipt or payload.id,
                amount=payload.amount,
                currency=payload.currency,
                status=payload.status,
                business_at=_business_at(payload.created_at),
            )
            for payload in orders_payload
        )
        payments = tuple(
            PaymentRecord(
                id=uuid4(),
                provider_payment_id=payload.id,
                provider_order_id=payload.order_id,
                receipt=receipt_by_order.get(payload.order_id, payload.order_id or payload.id),
                amount=payload.amount,
                currency=payload.currency,
                status=_payment_status(payload.status),
                captured=(
                    payload.captured
                    if payload.captured is not None
                    else payload.status == "captured"
                ),
                business_at=_business_at(payload.created_at),
            )
            for payload in payments_payload
        )
        refunds = tuple(
            RefundRecord(
                id=uuid4(),
                provider_refund_id=payload.id,
                provider_payment_id=payload.payment_id,
                amount=payload.amount,
                currency=payload.currency,
                status=payload.status,
                business_at=_business_at(payload.created_at),
            )
            for payload in refunds_payload
        )

        settlement_ids: dict[str, UUID] = {}
        settlements_by_id: dict[str, SettlementRecord] = {}
        for payload in settlements_payload:
            settlement_id = uuid4()
            settlement_ids[payload.id] = settlement_id
            record = SettlementRecord(
                id=settlement_id,
                provider_settlement_id=payload.id,
                amount=payload.amount,
                fee=payload.fees,
                tax=payload.tax,
                held_amount=0,
                currency=payload.currency,
                utr=payload.utr,
                status=payload.status,
                business_at=_business_at(payload.created_at),
            )
            settlements_by_id[payload.id] = record

        lines: list[SettlementLineRecord] = []
        for payload in recon_payload:
            settlement_id = settlement_ids.get(payload.settlement_id)
            if settlement_id is None:
                if not payload.settlement_utr:
                    raise RazorpayAdapterError(
                        "Razorpay source mapping failed: settlement UTR is required"
                    )
                settlement_id = uuid4()
                settlement_ids[payload.settlement_id] = settlement_id
                settlements_by_id[payload.settlement_id] = SettlementRecord(
                    id=settlement_id,
                    provider_settlement_id=payload.settlement_id or "unknown",
                    amount=0,
                    fee=0,
                    tax=0,
                    held_amount=0,
                    currency=payload.currency,
                    utr=payload.settlement_utr,
                    status="processed" if payload.settled else "created",
                    business_at=_business_at(payload.settled_at or payload.created_at),
                )
            settlement = settlements_by_id[payload.settlement_id]
            settlements_by_id[payload.settlement_id] = replace(
                settlement,
                fee=settlement.fee or payload.fee,
                tax=settlement.tax or payload.tax,
                held_amount=settlement.held_amount
                + (payload.amount if payload.on_hold else 0),
                utr=settlement.utr,
            )
            line_amount = payload.amount if payload.credit >= payload.debit else -payload.amount
            line_time = _business_at(payload.settled_at or payload.created_at)
            lines.append(
                SettlementLineRecord(
                    id=uuid4(),
                    settlement_id=settlement_id,
                    line_type=_line_type(payload.type),
                    reference=payload.payment_id or payload.order_id or payload.entity_id,
                    amount=line_amount,
                    currency=payload.currency,
                    business_at=line_time,
                )
            )
            if payload.fee:
                lines.append(
                    SettlementLineRecord(
                        id=uuid4(),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.fee,
                        reference=payload.entity_id,
                        amount=-payload.fee,
                        currency=payload.currency,
                        business_at=line_time,
                    )
                )
            if payload.tax:
                lines.append(
                    SettlementLineRecord(
                        id=uuid4(),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.tax,
                        reference=payload.entity_id,
                        amount=-payload.tax,
                        currency=payload.currency,
                        business_at=line_time,
                    )
                )

        settlements = tuple(settlements_by_id.values())
        return RazorpaySnapshot(
            razorpay_orders=orders,
            razorpay_payments=payments,
            razorpay_refunds=refunds,
            settlements=settlements,
            settlement_lines=tuple(lines),
        )


class DemoRazorpaySource(RazorpaySource):
    async def fetch_snapshot(self) -> RazorpaySnapshot:
        now = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        order_one = uuid4()
        order_two = uuid4()
        payment_one = uuid4()
        payment_two = uuid4()
        settlement_id = uuid4()
        return RazorpaySnapshot(
            razorpay_orders=(
                OrderRecord(order_one, "order_test_001", "TEST-0001", 125000, "INR", "paid", now),
                OrderRecord(order_two, "order_test_002", "TEST-0002", 99000, "INR", "paid", now),
            ),
            razorpay_payments=(
                PaymentRecord(
                    payment_one,
                    "pay_test_001",
                    "order_test_001",
                    "TEST-0001",
                    125000,
                    "INR",
                    RazorpayPaymentStatus.captured,
                    True,
                    now,
                ),
                PaymentRecord(
                    payment_two,
                    "pay_test_002",
                    "order_test_002",
                    "TEST-0002",
                    99000,
                    "INR",
                    RazorpayPaymentStatus.captured,
                    True,
                    now,
                ),
            ),
            razorpay_refunds=(
                RefundRecord(
                    uuid4(), "rfnd_test_001", "pay_test_002", 10000, "INR", "processed", now
                ),
            ),
            settlements=(
                SettlementRecord(
                    settlement_id,
                    "setl_test_001",
                    211500,
                    5000,
                    900,
                    0,
                    "INR",
                    "UTR-TEST-001",
                    "processed",
                    now,
                ),
            ),
            settlement_lines=(
                SettlementLineRecord(
                    uuid4(),
                    settlement_id,
                    SettlementLineType.payment,
                    "pay_test_001",
                    125000,
                    "INR",
                    now,
                ),
                SettlementLineRecord(
                    uuid4(),
                    settlement_id,
                    SettlementLineType.payment,
                    "pay_test_002",
                    99000,
                    "INR",
                    now,
                ),
                SettlementLineRecord(
                    uuid4(),
                    settlement_id,
                    SettlementLineType.refund,
                    "pay_test_002",
                    -10000,
                    "INR",
                    now,
                ),
            ),
        )
