from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from uuid import UUID, uuid5

from app.common.enums import (
    LedgerEntryType,
    ResultStatus,
    RazorpayPaymentStatus,
    SettlementLineType,
)
from app.common.money import calculate_fee, calculate_gst

DEMO_NAMESPACE = UUID("d8bddbbf-b8a5-58c0-b9a4-cce2f21ed471")
BASE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
DEFAULT_SEED = "razorrecon-v1"


def stable_id(kind: str, key: str) -> UUID:
    return _seeded_stable_id(DEFAULT_SEED, kind, key)


def _seeded_stable_id(seed: str, kind: str, key: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"{seed}:{kind}:{key}")


@dataclass(frozen=True, slots=True)
class LedgerEntrySeed:
    id: UUID
    reference: str
    entry_type: LedgerEntryType
    amount: int
    currency: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class RazorpayOrderSeed:
    id: UUID
    provider_order_id: str
    receipt: str
    amount: int
    currency: str
    status: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class RazorpayPaymentSeed:
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
class RazorpayRefundSeed:
    id: UUID
    provider_refund_id: str
    provider_payment_id: str
    amount: int
    currency: str
    status: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementSeed:
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
class SettlementLineSeed:
    id: UUID
    settlement_id: UUID
    line_type: SettlementLineType
    reference: str
    amount: int
    currency: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class BankCreditSeed:
    id: UUID
    settlement_id: UUID
    utr: str
    amount: int
    currency: str
    business_at: datetime


@dataclass(frozen=True, slots=True)
class MalformedRowSeed:
    id: UUID
    row_number: int
    source_type: str
    raw_payload: str
    parse_error: str


@dataclass(frozen=True, slots=True)
class TruthCaseSeed:
    case_id: UUID
    scenario_class: str
    scenario_tags: tuple[str, ...]
    amount: int
    matchable: bool
    expected_status: ResultStatus
    ledger_entry_id: UUID | None
    razorpay_order_id: UUID | None
    razorpay_payment_id: UUID | None
    razorpay_refund_id: UUID | None
    settlement_id: UUID | None
    bank_credit_id: UUID | None
    settlement_ids: tuple[UUID, ...] = ()
    bank_credit_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class DemoDataset:
    seed: str
    batch_id: UUID
    ledger_entries: tuple[LedgerEntrySeed, ...]
    razorpay_orders: tuple[RazorpayOrderSeed, ...]
    razorpay_payments: tuple[RazorpayPaymentSeed, ...]
    razorpay_refunds: tuple[RazorpayRefundSeed, ...]
    settlements: tuple[SettlementSeed, ...]
    settlement_lines: tuple[SettlementLineSeed, ...]
    bank_credits: tuple[BankCreditSeed, ...]
    provider_only_cases: tuple[TruthCaseSeed, ...]
    malformed_rows: tuple[MalformedRowSeed, ...]
    truth_cases: tuple[TruthCaseSeed, ...]
    scenario_counts: MappingProxyType
    source_row_count: int


def _seeded_provider_id(seed: str, prefix: str, kind: str, key: str) -> str:
    return f"{prefix}_{_seeded_stable_id(seed, kind, key).hex[:14]}"


def _business_time(index: int, *, offset_days: int = 0) -> datetime:
    return BASE_TIME + timedelta(days=index % 28 + offset_days, minutes=(index * 13) % 60)


def _amount(index: int) -> int:
    return 10_000 + ((index * 7_919) % 190_000)


def _scenario_tags(index: int) -> tuple[str, ...]:
    tags: list[str] = []
    if index < 40:
        tags.append("exact_id")
    if index < 24:
        tags.append("fee_gst")
    if 10 <= index < 26:
        tags.append("date_shift")
    if 20 <= index < 34:
        tags.append("fuzzy_reference")
    if 40 <= index < 48:
        tags.append("duplicate")
    if 80 <= index < 88:
        tags.append("missing_razorpay")
    if 50 <= index < 56:
        tags.append("missing_settlement")
    if 56 <= index < 60 or 68 <= index < 70:
        tags.append("missing_bank_credit")
    if 60 <= index < 68:
        tags.append("amount_mismatch")
    if 70 <= index < 80:
        tags.append("refund")
    if 90 <= index < 96:
        tags.append("held_release")
    if 100 <= index < 108:
        tags.append("ambiguous")
    return tuple(tags)


def _scenario_class(tags: tuple[str, ...]) -> str:
    priority = (
        "missing_razorpay",
        "missing_settlement",
        "missing_bank_credit",
        "duplicate",
        "amount_mismatch",
        "ambiguous",
        "refund",
        "held_release",
        "fuzzy_reference",
        "date_shift",
        "fee_gst",
        "exact_id",
    )
    return next((tag for tag in priority if tag in tags), "standard")


def _expected_status(tags: tuple[str, ...]) -> ResultStatus:
    if "missing_razorpay" in tags:
        return ResultStatus.missing_razorpay
    if "missing_settlement" in tags:
        return ResultStatus.missing_settlement
    if "missing_bank_credit" in tags:
        return ResultStatus.missing_bank_credit
    if "duplicate" in tags:
        return ResultStatus.duplicate
    if "amount_mismatch" in tags:
        return ResultStatus.amount_mismatch
    if "ambiguous" in tags:
        return ResultStatus.ambiguous
    return ResultStatus.matched


def _settlement_keys(index: int, tags: tuple[str, ...]) -> tuple[str, ...]:
    if "held_release" in tags:
        return (
            f"held-{index - 90:02d}",
            f"held-release-{index - 90:02d}",
        )
    if "missing_bank_credit" in tags:
        return ("missing-bank",)
    return ("normal",)


def build_demo_dataset(seed: str = DEFAULT_SEED) -> DemoDataset:
    """Build the fixed benchmark without touching a database or external service."""
    batch_id = _seeded_stable_id(seed, "batch", seed)
    ledger_entries: list[LedgerEntrySeed] = []
    razorpay_orders: list[RazorpayOrderSeed] = []
    razorpay_payments: list[RazorpayPaymentSeed] = []
    razorpay_refunds: list[RazorpayRefundSeed] = []
    settlements: list[SettlementSeed] = []
    settlement_lines: list[SettlementLineSeed] = []
    bank_credits: list[BankCreditSeed] = []
    truth_cases: list[TruthCaseSeed] = []
    payment_by_case: dict[int, RazorpayPaymentSeed] = {}
    refund_amount_by_case: dict[int, int] = {}

    for index in range(120):
        case_key = f"case-{index:03d}"
        tags = _scenario_tags(index)
        amount = _amount(index)
        ledger_id = _seeded_stable_id(seed, "ledger-entry", case_key)
        order_id = _seeded_stable_id(seed, "razorpay-order", case_key)
        provider_order_id = _seeded_provider_id(
            seed, "order", "razorpay-order", case_key
        )
        if "exact_id" in tags:
            reference = f"RCPT-{index:04d}"
            receipt = reference
        elif "fuzzy_reference" in tags:
            reference = f"INV/{index:04d}/ONLINE"
            receipt = f"invoice-{index:04d}"
        else:
            reference = f"INV-{index:04d}"
            receipt = f"checkout-{index:04d}"

        ledger_entry = LedgerEntrySeed(
            id=ledger_id,
            reference=reference,
            entry_type=LedgerEntryType.refund if "refund" in tags else LedgerEntryType.payment,
            amount=amount,
            currency="INR",
            business_at=_business_time(index),
        )
        ledger_entries.append(ledger_entry)

        order = RazorpayOrderSeed(
            id=order_id,
            provider_order_id=provider_order_id,
            receipt=receipt,
            amount=amount,
            currency="INR",
            status="paid" if index % 9 else "created",
            business_at=_business_time(index, offset_days=1 if "date_shift" in tags else 0),
        )
        razorpay_orders.append(order)

        payment_missing = "missing_razorpay" in tags
        if not payment_missing:
            payment_amount = amount + 500 if "amount_mismatch" in tags else amount
            payment = RazorpayPaymentSeed(
                id=_seeded_stable_id(seed, "razorpay-payment", case_key),
                provider_payment_id=_seeded_provider_id(
                    seed, "pay", "razorpay-payment", case_key
                ),
                provider_order_id=provider_order_id,
                receipt=receipt,
                amount=payment_amount,
                currency="INR",
                status=RazorpayPaymentStatus.captured,
                captured=True,
                business_at=_business_time(
                    index, offset_days=2 if "date_shift" in tags else 0
                ),
            )
            razorpay_payments.append(payment)
            payment_by_case[index] = payment

            if "duplicate" in tags:
                razorpay_payments.append(
                    RazorpayPaymentSeed(
                        id=_seeded_stable_id(
                            seed, "razorpay-payment", f"{case_key}-duplicate"
                        ),
                        provider_payment_id=_seeded_provider_id(
                            seed,
                            "pay",
                            "razorpay-payment",
                            f"{case_key}-duplicate",
                        ),
                        provider_order_id=provider_order_id,
                        receipt=receipt,
                        amount=payment_amount,
                        currency="INR",
                        status=RazorpayPaymentStatus.captured,
                        captured=True,
                        business_at=payment.business_at + timedelta(minutes=2),
                    )
                )

            if "refund" in tags:
                refund_amount = amount if index % 2 else amount // 2
                refund_amount_by_case[index] = refund_amount
                razorpay_refunds.append(
                    RazorpayRefundSeed(
                        id=_seeded_stable_id(seed, "razorpay-refund", case_key),
                        provider_refund_id=_seeded_provider_id(
                            seed, "rfnd", "razorpay-refund", case_key
                        ),
                        provider_payment_id=payment.provider_payment_id,
                        amount=refund_amount,
                        currency="INR",
                        status="processed",
                        business_at=payment.business_at + timedelta(days=1),
                    )
                )

        truth_cases.append(
            TruthCaseSeed(
                case_id=_seeded_stable_id(seed, "evaluation-case", case_key),
                scenario_class=_scenario_class(tags),
                scenario_tags=tags,
                amount=amount,
                matchable="missing_razorpay" not in tags,
                expected_status=_expected_status(tags),
                ledger_entry_id=ledger_id,
                razorpay_order_id=order.id,
                razorpay_payment_id=(payment_by_case[index].id if index in payment_by_case else None),
                razorpay_refund_id=(
                    _seeded_stable_id(seed, "razorpay-refund", case_key)
                    if "refund" in tags
                    else None
                ),
                settlement_id=(
                    _seeded_stable_id(
                        seed, "settlement", _settlement_keys(index, tags)[0]
                    )
                    if index in payment_by_case and "missing_settlement" not in tags
                    else None
                ),
                bank_credit_id=(
                    _seeded_stable_id(
                        seed, "bank-credit", _settlement_keys(index, tags)[0]
                    )
                    if index in payment_by_case
                    and "missing_settlement" not in tags
                    and "missing_bank_credit" not in tags
                    else None
                ),
                settlement_ids=(
                    tuple(
                        _seeded_stable_id(seed, "settlement", key)
                        for key in _settlement_keys(index, tags)
                    )
                    if index in payment_by_case and "missing_settlement" not in tags
                    else ()
                ),
                bank_credit_ids=(
                    tuple(
                        _seeded_stable_id(seed, "bank-credit", key)
                        for key in _settlement_keys(index, tags)
                    )
                    if index in payment_by_case
                    and "missing_settlement" not in tags
                    and "missing_bank_credit" not in tags
                    else ()
                ),
            )
        )

    provider_only_cases: list[TruthCaseSeed] = []
    for index in range(6):
        case_key = f"provider-only-{index:03d}"
        amount = _amount(120 + index)
        provider_order_id = _seeded_provider_id(
            seed, "order", "razorpay-order", case_key
        )
        provider_payment_id = _seeded_provider_id(
            seed, "pay", "razorpay-payment", case_key
        )
        order = RazorpayOrderSeed(
            id=_seeded_stable_id(seed, "razorpay-order", case_key),
            provider_order_id=provider_order_id,
            receipt=f"external-{index:04d}",
            amount=amount,
            currency="INR",
            status="paid",
            business_at=_business_time(120 + index),
        )
        payment = RazorpayPaymentSeed(
            id=_seeded_stable_id(seed, "razorpay-payment", case_key),
            provider_payment_id=provider_payment_id,
            provider_order_id=provider_order_id,
            receipt=order.receipt,
            amount=amount,
            currency="INR",
            status=RazorpayPaymentStatus.captured,
            captured=True,
            business_at=order.business_at,
        )
        razorpay_orders.append(order)
        razorpay_payments.append(payment)
        case = TruthCaseSeed(
            case_id=_seeded_stable_id(seed, "evaluation-case", case_key),
            scenario_class="missing_ledger",
            scenario_tags=("missing_ledger",),
            amount=amount,
            matchable=False,
            expected_status=ResultStatus.missing_ledger,
            ledger_entry_id=None,
            razorpay_order_id=order.id,
            razorpay_payment_id=payment.id,
            razorpay_refund_id=None,
            settlement_id=None,
            bank_credit_id=None,
            settlement_ids=(),
            bank_credit_ids=(),
        )
        provider_only_cases.append(case)
        truth_cases.append(case)

    ordinary_entries: dict[
        str, list[tuple[int, RazorpayPaymentSeed, int, int, int]]
    ] = {"normal": [], "missing-bank": []}
    for index in range(120):
        tags = _scenario_tags(index)
        payment = payment_by_case.get(index)
        if payment is None or "missing_settlement" in tags:
            continue
        refund_amount = refund_amount_by_case.get(index, 0)
        fee = calculate_fee(payment.amount)
        gst = calculate_gst(fee)
        if "held_release" not in tags:
            group_key = "missing-bank" if "missing_bank_credit" in tags else "normal"
            ordinary_entries[group_key].append(
                (index, payment, refund_amount, fee, gst)
            )
            continue

        case_key = f"held-{index - 90:02d}"
        hold = 1_000
        first_settlement_id = _seeded_stable_id(seed, "settlement", case_key)
        first_settlement = SettlementSeed(
            id=first_settlement_id,
            provider_settlement_id=_seeded_provider_id(
                seed, "setl", "settlement", case_key
            ),
            amount=payment.amount - refund_amount - fee - gst - hold,
            fee=fee,
            tax=gst,
            held_amount=hold,
            currency="INR",
            utr=f"UTR{_seeded_stable_id(seed, 'utr', case_key).hex[:18].upper()}",
            status="processed",
            business_at=_business_time(160 + index),
        )
        settlements.append(first_settlement)
        settlement_lines.extend(
            (
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{case_key}-payment"
                    ),
                    settlement_id=first_settlement_id,
                    line_type=SettlementLineType.payment,
                    reference=payment.provider_payment_id,
                    amount=payment.amount,
                    currency="INR",
                    business_at=first_settlement.business_at,
                ),
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{case_key}-refund"
                    ),
                    settlement_id=first_settlement_id,
                    line_type=SettlementLineType.refund,
                    reference=payment.provider_payment_id,
                    amount=-refund_amount,
                    currency="INR",
                    business_at=first_settlement.business_at,
                ),
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{case_key}-fee"
                    ),
                    settlement_id=first_settlement_id,
                    line_type=SettlementLineType.fee,
                    reference=f"FEE-{index:04d}",
                    amount=-fee,
                    currency="INR",
                    business_at=first_settlement.business_at,
                ),
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{case_key}-tax"
                    ),
                    settlement_id=first_settlement_id,
                    line_type=SettlementLineType.tax,
                    reference=f"GST-{index:04d}",
                    amount=-gst,
                    currency="INR",
                    business_at=first_settlement.business_at,
                ),
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{case_key}-hold"
                    ),
                    settlement_id=first_settlement_id,
                    line_type=SettlementLineType.hold,
                    reference=f"HOLD-{index:04d}",
                    amount=-hold,
                    currency="INR",
                    business_at=first_settlement.business_at,
                ),
            )
        )
        release_key = f"held-release-{index - 90:02d}"
        release_id = _seeded_stable_id(seed, "settlement", release_key)
        release = SettlementSeed(
            id=release_id,
            provider_settlement_id=_seeded_provider_id(
                seed, "setl", "settlement", release_key
            ),
            amount=hold,
            fee=0,
            tax=0,
            held_amount=0,
            currency="INR",
            utr=f"UTR{_seeded_stable_id(seed, 'utr', release_key).hex[:18].upper()}",
            status="processed",
            business_at=first_settlement.business_at + timedelta(days=2),
        )
        settlements.append(release)
        settlement_lines.extend(
            (
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{release_key}-release"
                    ),
                    settlement_id=release_id,
                    line_type=SettlementLineType.release,
                    reference=first_settlement.provider_settlement_id,
                    amount=hold,
                    currency="INR",
                    business_at=release.business_at,
                ),
                SettlementLineSeed(
                    id=_seeded_stable_id(
                        seed, "settlement-line", f"{release_key}-adjustment"
                    ),
                    settlement_id=release_id,
                    line_type=SettlementLineType.adjustment,
                    reference=f"ADJ-{index:04d}",
                    amount=0,
                    currency="INR",
                    business_at=release.business_at,
                ),
            )
        )
        bank_credits.extend(
            (
                BankCreditSeed(
                    id=_seeded_stable_id(seed, "bank-credit", case_key),
                    settlement_id=first_settlement_id,
                    utr=first_settlement.utr,
                    amount=first_settlement.amount,
                    currency="INR",
                    business_at=first_settlement.business_at + timedelta(days=1),
                ),
                BankCreditSeed(
                    id=_seeded_stable_id(seed, "bank-credit", release_key),
                    settlement_id=release_id,
                    utr=release.utr,
                    amount=release.amount,
                    currency="INR",
                    business_at=release.business_at + timedelta(days=1),
                ),
            )
        )

    for group_key, entries in ordinary_entries.items():
        if not entries:
            continue
        settlement_id = _seeded_stable_id(seed, "settlement", group_key)
        settlement_amount = sum(
            payment.amount - refund_amount - fee - gst
            for _, payment, refund_amount, fee, gst in entries
        )
        settlement = SettlementSeed(
            id=settlement_id,
            provider_settlement_id=_seeded_provider_id(
                seed, "setl", "settlement", group_key
            ),
            amount=settlement_amount,
            fee=sum(fee for _, _, _, fee, _ in entries),
            tax=sum(gst for _, _, _, _, gst in entries),
            held_amount=0,
            currency="INR",
            utr=f"UTR{_seeded_stable_id(seed, 'utr', group_key).hex[:18].upper()}",
            status="processed",
            business_at=BASE_TIME + timedelta(days=31 if group_key == "normal" else 32),
        )
        settlements.append(settlement)
        for index, payment, refund_amount, fee, gst in entries:
            case_key = f"case-{index:03d}"
            settlement_lines.extend(
                (
                    SettlementLineSeed(
                        id=_seeded_stable_id(
                            seed, "settlement-line", f"{group_key}-{case_key}-payment"
                        ),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.payment,
                        reference=payment.provider_payment_id,
                        amount=payment.amount,
                        currency="INR",
                        business_at=settlement.business_at,
                    ),
                    SettlementLineSeed(
                        id=_seeded_stable_id(
                            seed, "settlement-line", f"{group_key}-{case_key}-fee"
                        ),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.fee,
                        reference=f"FEE-{index:04d}",
                        amount=-fee,
                        currency="INR",
                        business_at=settlement.business_at,
                    ),
                    SettlementLineSeed(
                        id=_seeded_stable_id(
                            seed, "settlement-line", f"{group_key}-{case_key}-tax"
                        ),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.tax,
                        reference=f"GST-{index:04d}",
                        amount=-gst,
                        currency="INR",
                        business_at=settlement.business_at,
                    ),
                )
            )
            if refund_amount:
                settlement_lines.append(
                    SettlementLineSeed(
                        id=_seeded_stable_id(
                            seed, "settlement-line", f"{group_key}-{case_key}-refund"
                        ),
                        settlement_id=settlement_id,
                        line_type=SettlementLineType.refund,
                        reference=payment.provider_payment_id,
                        amount=-refund_amount,
                        currency="INR",
                        business_at=settlement.business_at,
                    )
                )
        if group_key == "normal":
            bank_credits.append(
                BankCreditSeed(
                    id=_seeded_stable_id(seed, "bank-credit", group_key),
                    settlement_id=settlement_id,
                    utr=settlement.utr,
                    amount=settlement.amount,
                    currency="INR",
                    business_at=settlement.business_at + timedelta(days=1),
                )
            )

    malformed_rows = tuple(
        MalformedRowSeed(
            id=_seeded_stable_id(seed, "malformed-row", f"row-{index:02d}"),
            row_number=10_000 + index,
            source_type="razorpay_payment",
            raw_payload=f'{{"id":"broken-{index:02d}","amount":"not-an-integer"}}',
            parse_error="amount must be an integer INR paise value",
        )
        for index in range(6)
    )

    scenario_counts: dict[str, int] = {}
    for case in truth_cases:
        for tag in case.scenario_tags:
            scenario_counts[tag] = scenario_counts.get(tag, 0) + 1
    scenario_counts["malformed"] = len(malformed_rows)
    source_row_count = sum(
        (
            len(ledger_entries),
            len(razorpay_orders),
            len(razorpay_payments),
            len(razorpay_refunds),
            len(settlements),
            len(bank_credits),
            len(malformed_rows),
        )
    )

    return DemoDataset(
        seed=seed,
        batch_id=batch_id,
        ledger_entries=tuple(ledger_entries),
        razorpay_orders=tuple(razorpay_orders),
        razorpay_payments=tuple(razorpay_payments),
        razorpay_refunds=tuple(razorpay_refunds),
        settlements=tuple(settlements),
        settlement_lines=tuple(settlement_lines),
        bank_credits=tuple(bank_credits),
        provider_only_cases=tuple(provider_only_cases),
        malformed_rows=malformed_rows,
        truth_cases=tuple(truth_cases),
        scenario_counts=MappingProxyType(scenario_counts),
        source_row_count=source_row_count,
    )
