# RoboRecon

RoboRecon closes the finance-operations loop between a merchant's internal ledger,
Razorpay payment activity, and the settlement money received in the bank.

## Source Records

**Merchant Ledger Entry**:
The merchant's internal record of an expected payment or refund in INR.
_Avoid_: Internal payment, transaction

**Razorpay Order**:
A checkout intent that can group one or more Razorpay payment attempts.
_Avoid_: Sale, merchant order

**Razorpay Payment**:
A Razorpay record of a payment attempt, including whether money was captured.
_Avoid_: Provider payment, external payment

**Razorpay Refund**:
A Razorpay record returning all or part of a captured payment.
_Avoid_: Reversal

**Settlement**:
A Razorpay payout statement grouping captured payments, refunds, fees, and tax into a net amount payable to the merchant.
_Avoid_: Bank transfer, payout transaction

**Bank Credit**:
The bank-side record of money received for a Settlement.
_Avoid_: Settlement, bank payment

**Held Amount**:
A portion of captured payment value intentionally withheld from the current Settlement.
_Avoid_: Missing money, fee

**Release Adjustment**:
A later Settlement line that makes a previously Held Amount payable to the merchant.
_Avoid_: Refund, correction

## Reconciliation

**Reconciliation Run**:
One execution against a fixed source-data batch across Ledger-to-Razorpay and Razorpay-to-Settlement stages; its results are immutable after completion.
_Avoid_: Reconciliation, sync

**Closed Finance-Ops Loop**:
A completed Reconciliation Run whose evidence and metrics have been inspected and whose Exception workflow has demonstrated a terminal Review Decision.
_Avoid_: Fully matched batch

**Match Link**:
A claim, supported by evidence, that source records represent the same payment lifecycle or payout obligation.
_Avoid_: Pair, mapping

**Auto-resolution**:
A final outcome produced by deterministic policy without human approval.
_Avoid_: AI match, automatic suggestion

**Exception**:
A case that deterministic policy cannot safely close and therefore requires human review.
_Avoid_: Error, failed match

**Open Exception**:
An Exception that has not yet received a terminal Review Decision.
_Avoid_: Unresolved money

**Review Decision**:
A human approval or rejection of a proposed resolution, recorded with its evidence and actor.
_Avoid_: Override

**Confirmed No-Match**:
A terminal Review Decision that closes an Exception without accepting a Match Link.
_Avoid_: Open exception, failed review

## Evaluation

**Ground Truth**:
The hidden benchmark describing expected links and outcomes for seeded records; it is available to evaluation only and never to matching.
_Avoid_: Seed metadata, matcher hints

**Evaluation Case**:
One hidden benchmark unit describing the expected treatment of related seeded source records and its scenario class.
_Avoid_: Source record, exception

**Match Rate**:
Correctly resolved matchable Evaluation Cases divided by all matchable Evaluation Cases, reported by scenario class and overall.
_Avoid_: Success rate

**Precision**:
Correct auto-resolved Match Links divided by all auto-resolved Match Links.
_Avoid_: Confidence

**False Positive**:
An auto-resolved Match Link that contradicts Ground Truth.
_Avoid_: Low-confidence match

**Auto-resolution Rate**:
Evaluation cases closed by deterministic policy divided by all evaluation cases in the Reconciliation Run.
_Avoid_: Match rate

**Money Reconciled**:
The INR gross value of Merchant Ledger Entries correctly closed by a Reconciliation Run; Settlement net value is reported separately to avoid double counting.
_Avoid_: Processed volume

**Money Unresolved**:
The INR gross value of Merchant Ledger Entries without an accepted Match Link, including both Open Exceptions and Confirmed No-Match outcomes.
_Avoid_: Open exception value
