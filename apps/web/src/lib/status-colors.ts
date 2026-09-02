const positive = "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
const warning = "border-amber-400/30 bg-amber-400/10 text-amber-200";
const danger = "border-rose-400/30 bg-rose-400/10 text-rose-200";
const neutral = "border-slate-400/30 bg-slate-400/10 text-slate-200";
const active = "border-cyan-400/30 bg-cyan-400/10 text-cyan-200";

export const resultStatusStyles: Record<string, string> = {
  matched: positive,
  ambiguous: warning,
  duplicate: "border-violet-400/30 bg-violet-400/10 text-violet-200",
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
  matched: "bg-green-100 text-green-800 border-green-200",
  matched_with_fee: "bg-emerald-100 text-emerald-800 border-emerald-200",
  amount_mismatch: "bg-amber-100 text-amber-800 border-amber-200",
  missing_internal: "bg-red-100 text-red-800 border-red-200",
  missing_external: "bg-orange-100 text-orange-800 border-orange-200",
  duplicate: "bg-purple-100 text-purple-800 border-purple-200",
  disputed: "bg-rose-100 text-rose-800 border-rose-200",
};

export const paymentStatusStyles: Record<string, string> = {
  succeeded: "bg-green-100 text-green-800 border-green-200",
  pending: "bg-yellow-100 text-yellow-800 border-yellow-200",
  failed: "bg-red-100 text-red-800 border-red-200",
  refunded: "bg-blue-100 text-blue-800 border-blue-200",
  partially_refunded: "bg-sky-100 text-sky-800 border-sky-200",
  disputed: "bg-rose-100 text-rose-800 border-rose-200",
};

export function humanizeStatus(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
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
