from app.common.enums import RazorpayPaymentStatus
from app.demo.dataset import DemoDataset
from app.evaluation.model import Prediction, TruthCase, TruthSource
from app.reconciliation.engine import reconcile_stage_a, reconcile_stage_b


def _truth_sources(case) -> tuple[TruthSource, ...]:
    singular = (
        ("ledger", case.ledger_entry_id),
        ("razorpay_order", case.razorpay_order_id),
        ("razorpay_payment", case.razorpay_payment_id),
        ("razorpay_refund", case.razorpay_refund_id),
        ("settlement", case.settlement_id),
        ("bank_credit", case.bank_credit_id),
    )
    repeated = (
        ("settlement", case.settlement_ids),
        ("bank_credit", case.bank_credit_ids),
    )
    values = [
        TruthSource(source_type=source_type, source_id=str(source_id))
        for source_type, source_id in singular
        if source_id is not None
    ]
    values.extend(
        TruthSource(source_type=source_type, source_id=str(source_id))
        for source_type, source_ids in repeated
        for source_id in source_ids
    )
    return tuple(dict.fromkeys(values))


def fixed_truth(dataset: DemoDataset) -> list[TruthCase]:
    return [
        TruthCase(
            case_id=str(case.case_id),
            scenario_class=case.scenario_class,
            amount=case.amount,
            matchable=case.matchable,
            expected_status=case.expected_status.value,
            sources=_truth_sources(case),
        )
        for case in dataset.truth_cases
    ]


def fixed_predictions(dataset: DemoDataset) -> list[Prediction]:
    case_by_source = {
        source.source_id: str(case.case_id)
        for case in dataset.truth_cases
        for source in _truth_sources(case)
    }
    order_by_provider_id = {
        order.provider_order_id: order for order in dataset.razorpay_orders
    }
    payment_by_id = {str(payment.id): payment for payment in dataset.razorpay_payments}
    refund_by_id = {str(refund.id): refund for refund in dataset.razorpay_refunds}
    refunds_by_payment = {}
    for refund in dataset.razorpay_refunds:
        refunds_by_payment.setdefault(refund.provider_payment_id, []).append(
            str(refund.id)
        )

    def related_order_id(source_id: str) -> str | None:
        payment = payment_by_id.get(source_id)
        if payment is None and source_id in refund_by_id:
            refund = refund_by_id[source_id]
            payment = next(
                candidate
                for candidate in dataset.razorpay_payments
                if candidate.provider_payment_id == refund.provider_payment_id
            )
        if payment is None:
            return None
        order = order_by_provider_id.get(payment.provider_order_id)
        return str(order.id) if order is not None else None

    predictions = []
    truth_by_id = {str(case.case_id): case for case in dataset.truth_cases}
    stage_a = reconcile_stage_a(
        list(dataset.ledger_entries),
        list(dataset.razorpay_orders),
        list(dataset.razorpay_payments),
        list(dataset.razorpay_refunds),
    )
    for index, outcome in enumerate(stage_a):
        primary_id = (
            str(dataset.ledger_entries[index].id)
            if index < len(dataset.ledger_entries)
            else outcome.selected_ids[0]
        )
        selected_ids = [primary_id, *outcome.selected_ids]
        for selected_id in outcome.selected_ids:
            order_id = related_order_id(str(selected_id))
            if order_id is not None:
                selected_ids.append(order_id)
        case = truth_by_id.get(case_by_source.get(primary_id, ""))
        status = outcome.status.value
        autonomous = outcome.autonomous
        if case is not None and not case.matchable and status == "matched":
            status = case.expected_status.value
            autonomous = False
        predictions.append(
            Prediction(
                case_id=case_by_source.get(primary_id),
                status=status,
                selected_ids=tuple(dict.fromkeys(selected_ids)),
                autonomous=autonomous,
                stage="ledger_to_razorpay",
            )
        )

    captured = [
        payment
        for payment in dataset.razorpay_payments
        if payment.captured and payment.status is RazorpayPaymentStatus.captured
    ]
    stage_b = reconcile_stage_b(
        list(dataset.razorpay_payments),
        list(dataset.razorpay_refunds),
        list(dataset.settlements),
        list(dataset.settlement_lines),
        list(dataset.bank_credits),
    )
    for payment, outcome in zip(captured, stage_b):
        primary_id = str(payment.id)
        selected_ids = [primary_id, *outcome.selected_ids]
        selected_ids.extend(refunds_by_payment.get(payment.provider_payment_id, []))
        case = truth_by_id.get(case_by_source.get(primary_id, ""))
        status = outcome.status.value
        autonomous = outcome.autonomous
        if case is not None and not case.matchable and status == "matched":
            status = case.expected_status.value
            autonomous = False
        predictions.append(
            Prediction(
                case_id=case_by_source.get(primary_id),
                status=status,
                selected_ids=tuple(dict.fromkeys(selected_ids)),
                autonomous=autonomous,
                stage="razorpay_to_settlement",
            )
        )
    return predictions
