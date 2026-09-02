const positive = "border-success/30 bg-success/10 text-success";
const warning = "border-warning/30 bg-warning/10 text-warning";
const danger = "border-danger/30 bg-danger/10 text-danger";
const neutral = "border-neutral/30 bg-neutral/10 text-neutral";
const active = "border-primary/30 bg-primary/10 text-primary";
const duplicate = "border-duplicate/30 bg-duplicate/10 text-duplicate";

export const resultStatusStyles: Record<string, string> = {
  matched: positive,
  ambiguous: warning,
  duplicate,
  missing_razorpay: danger,
  missing_ledger: danger,
  missing_settlement: danger,
  missing_bank_credit: warning,
  amount_mismatch: warning,
  malformed: danger,
  confirmed_no_match: neutral,
};

export const runStatusStyles: Record<string, string> = {
  running: active,
  completed: positive,
  failed: danger,
};

export const batchStatusStyles: Record<string, string> = {
  pending: warning,
  running: active,
  completed: positive,
  failed: danger,
};

export const reconciliationStateStyles: Record<string, string> = {
  autonomous: positive,
  matched: positive,
  open: warning,
  approved: positive,
  rejected: danger,
  unreconciled: neutral,
};

export const transactionStatusStyles: Record<string, string> = {
  paid: positive,
  captured: positive,
  credited: positive,
  processed: active,
  authorized: active,
  refunded: neutral,
  partially_refunded: warning,
  failed: danger,
  invalid: danger,
  created: neutral,
  payment: active,
  refund: warning,
};

export const reconciliationStatusStyles: Record<string, string> = {
  matched: positive,
  matched_with_fee: "border-success/50 bg-success/5 text-success",
  amount_mismatch: warning,
  missing_internal: danger,
  missing_external: "border-warning/50 bg-warning/5 text-warning",
  duplicate,
  disputed: "border-danger/50 bg-danger/5 text-danger",
};

export const paymentStatusStyles: Record<string, string> = {
  succeeded: positive,
  pending: warning,
  failed: danger,
  refunded: neutral,
  partially_refunded: "border-warning/50 bg-warning/5 text-warning",
  disputed: "border-danger/50 bg-danger/5 text-danger",
};

export function humanizeStatus(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_.-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .replace(/\bAi\b/g, "AI")
    .replace(/\bId\b/g, "ID")
    .replace(/\bInr\b/g, "INR");
}

export function statusClass(value: string): string {
  return (
    resultStatusStyles[value] ??
    runStatusStyles[value] ??
    batchStatusStyles[value] ??
    reconciliationStateStyles[value] ??
    transactionStatusStyles[value] ??
    neutral
  );
}
