import enum


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"
    disputed = "disputed"


class PaymentMethod(str, enum.Enum):
    card = "card"
    paypal_wallet = "paypal_wallet"
    bank_transfer = "bank_transfer"
    direct_debit = "direct_debit"


class StripePaymentType(str, enum.Enum):
    payment_intent = "payment_intent"
    charge = "charge"
    refund = "refund"
    dispute = "dispute"


class PaypalPaymentType(str, enum.Enum):
    order = "order"
    capture = "capture"
    authorization = "authorization"
    refund = "refund"
    dispute = "dispute"


class BankTransferType(str, enum.Enum):
    sepa_credit = "sepa_credit"
    sepa_direct_debit = "sepa_direct_debit"
    swift = "swift"
    domestic = "domestic"


class ReconciliationStatus(str, enum.Enum):
    matched = "matched"
    matched_with_fee = "matched_with_fee"
    amount_mismatch = "amount_mismatch"
    missing_internal = "missing_internal"
    missing_external = "missing_external"
    duplicate = "duplicate"
    disputed = "disputed"


class BatchKind(str, enum.Enum):
    demo = "demo"
    test_mode_sync = "test_mode_sync"


class BatchStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class LedgerEntryType(str, enum.Enum):
    payment = "payment"
    refund = "refund"


class RazorpayPaymentStatus(str, enum.Enum):
    created = "created"
    authorized = "authorized"
    captured = "captured"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class SettlementLineType(str, enum.Enum):
    payment = "payment"
    refund = "refund"
    transfer = "transfer"
    fee = "fee"
    tax = "tax"
    hold = "hold"
    release = "release"
    adjustment = "adjustment"


class RunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class ReconciliationStage(str, enum.Enum):
    ledger_to_razorpay = "ledger_to_razorpay"
    razorpay_to_settlement = "razorpay_to_settlement"


class ResultStatus(str, enum.Enum):
    matched = "matched"
    ambiguous = "ambiguous"
    duplicate = "duplicate"
    missing_razorpay = "missing_razorpay"
    missing_ledger = "missing_ledger"
    missing_settlement = "missing_settlement"
    missing_bank_credit = "missing_bank_credit"
    amount_mismatch = "amount_mismatch"
    malformed = "malformed"
    confirmed_no_match = "confirmed_no_match"


class ExceptionStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    rejected = "rejected"


class ReviewAction(str, enum.Enum):
    approve = "approve"
    reject = "reject"


class AuditEventType(str, enum.Enum):
    batch_created = "batch.created"
    demo_reset_completed = "demo.reset.completed"
    razorpay_sync_started = "razorpay.sync.started"
    razorpay_sync_completed = "razorpay.sync.completed"
    razorpay_sync_failed = "razorpay.sync.failed"
    run_started = "run.started"
    run_completed = "run.completed"
    run_failed = "run.failed"
    result_persisted = "result.persisted"
    ai_tool_called = "ai.tool.called"
    ai_recommendation = "ai.recommendation"
    review_approved = "review.approved"
    review_rejected = "review.rejected"
