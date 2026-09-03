import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { Alert } from "@/components/alert";
import { PageState, RetryButton } from "@/components/page-state";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useTransactions, type TransactionFilters } from "@/hooks/use-roborecon";
import { formatDateTime, formatInr, formatInteger } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { TransactionRecord } from "@/types/api";

const MALFORMED_RECORD_MESSAGE = "This source record could not be read. Review the source data.";

const sourceTypes = [
  ["", "All record types"],
  ["ledger", "Ledger"],
  ["razorpay_order", "Razorpay order"],
  ["razorpay_payment", "Razorpay payment"],
  ["razorpay_refund", "Razorpay refund"],
  ["settlement", "Settlement"],
  ["settlement_line", "Settlement line"],
  ["bank_credit", "Bank credit"],
  ["quarantine", "Needs attention"],
] as const;

const statuses = [
  ["", "All statuses"],
  ["payment", "Payment"],
  ["refund", "Refund"],
  ["created", "Created"],
  ["attempted", "Attempted"],
  ["pending", "Pending"],
  ["initiated", "Initiated"],
  ["authorized", "Authorized"],
  ["captured", "Captured"],
  ["paid", "Paid"],
  ["processed", "Processed"],
  ["credited", "Credited"],
  ["refunded", "Refunded"],
  ["partially_refunded", "Partially refunded"],
  ["reversed", "Reversed"],
  ["partially_processed", "Partially processed"],
  ["quarantined", "Quarantined"],
  ["invalid", "Invalid"],
  ["failed", "Failed"],
] as const;

const reconciliationStates = [
  ["", "All match states"],
  ["matched", "Matched"],
  ["unreconciled", "Unreconciled"],
  ["open", "Open"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
] as const;

function RelationshipLinks({ row }: { row: TransactionRecord }) {
  const links = [
    row.runId ? <Link key="run" to={`/runs/${row.runId}`} className="text-primary hover:text-primary/80">Run {row.runId}</Link> : null,
    row.resultId && row.runId ? <Link key="result" to={`/runs/${row.runId}#result-${row.resultId}`} className="text-primary hover:text-primary/80">Result {row.resultId}</Link> : null,
    row.exceptionId ? <Link key="exception" to={`/exceptions/${row.exceptionId}`} className="text-warning hover:text-warning/80">Exception {row.exceptionId}</Link> : null,
  ].filter((link) => link !== null);

  return links.length > 0 ? <div className="flex flex-col gap-1 text-xs">{links}</div> : <span className="text-xs text-muted-foreground">No linked evidence</span>;
}

const columns: ColumnDef<TransactionRecord, unknown>[] = [
  {
    id: "source",
    header: "Source",
    cell: ({ row }) => {
      const transaction = row.original;
      const malformed = Boolean(transaction.parseError) || transaction.sourceType === "quarantine";
      return (
        <div className="min-w-44">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-foreground">{humanizeStatus(transaction.sourceType)}</span>
            {malformed && <span className="rounded border border-danger/30 bg-danger/10 px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-[0.1em] text-danger">Invalid row</span>}
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{transaction.sourceId ?? "No record ID"}</p>
           <p className="mt-1 text-xs text-primary">{transaction.reference ?? "No reference"}</p>
            {malformed && <p className="mt-1 max-w-xs text-xs text-danger">{MALFORMED_RECORD_MESSAGE}</p>}
        </div>
      );
    },
  },
  {
    id: "amount",
    header: "Amount",
    cell: ({ row }) => <span className="font-mono tabular-nums">{formatInr(row.original.amount)}</span>,
  },
  {
    id: "status",
    header: "Status",
    cell: ({ row }) => <StatusBadge value={row.original.status} />,
  },
  {
    id: "reconciliation",
    header: "Reconciliation",
    cell: ({ row }) => <StatusBadge value={row.original.reconciliationState} />,
  },
  {
    id: "businessAt",
    header: "Business time",
    cell: ({ row }) => <span className="text-xs text-muted-foreground">{formatDateTime(row.original.businessAt)}</span>,
  },
  {
    id: "relationships",
    header: "Related evidence",
    cell: ({ row }) => <RelationshipLinks row={row.original} />,
  },
];

export function TransactionsPage() {
  const [searchParams] = useSearchParams();
  const citationSourceType = searchParams.get("source") ?? undefined;
  const citationSourceId = searchParams.get("sourceId") ?? undefined;
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Pick<TransactionFilters, "sourceType" | "status" | "reconciliationState" | "sourceId">>({ sourceType: citationSourceType, sourceId: citationSourceId });
  const pageSize = 25;
  const transactions = useTransactions({ page, pageSize, ...filters });

  const updateFilter = (name: keyof typeof filters, value: string) => {
    setPage(1);
    setFilters((current) => ({ ...current, [name]: value || undefined }));
  };

  if (transactions.isLoading) {
    return <PageState kind="loading" headingLevel="h1" title="Loading records…" description="Getting records from the selected batch." />;
  }

  if (transactions.isError) {
    return <PageState kind="error" headingLevel="h1" title="Could not load records" description={transactions.error.message} action={<RetryButton onClick={() => void transactions.refetch()} />} />;
  }

  const data = transactions.data;
  if (!data) {
    return <PageState kind="error" headingLevel="h1" title="Records are not available" description="No records were returned." />;
  }

  const displayData = data;

  return (
    <div className="page-stack">
      <PageHeader
        title="Source records"
        description="All payment records in one place, with filters and links to evidence."
        actions={<p className="font-mono text-xs text-muted-foreground">{formatInteger(displayData.total)} records</p>}
      />

      {citationSourceId && (
        <Alert>
          Source record: <span className="font-mono">{citationSourceId}</span>. Showing it if it is in this batch.
        </Alert>
      )}

      <section className="filter-panel grid gap-3 sm:grid-cols-3" aria-label="Record filters">
        <label className="field-label" htmlFor="source-type">
          Record type
          <Select id="source-type" value={filters.sourceType ?? ""} onChange={(event) => updateFilter("sourceType", event.target.value)}>
            {sourceTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="field-label" htmlFor="status">
          Status
          <Select id="status" value={filters.status ?? ""} onChange={(event) => updateFilter("status", event.target.value)}>
            {statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="field-label" htmlFor="reconciliation-state">
          Match state
          <Select id="reconciliation-state" value={filters.reconciliationState ?? ""} onChange={(event) => updateFilter("reconciliationState", event.target.value)}>
            {reconciliationStates.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
      </section>

      <Card className="gap-0 py-0">
        <CardHeader className="panel-header">
          <CardTitle className="text-sm font-medium">Payment records</CardTitle>
          {transactions.isFetching && !transactions.isLoading && (
             <span role="status" aria-label="Updating records…" className="text-xs text-primary">
               Updating records…
            </span>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            data={displayData.items}
            columns={columns}
            getRowId={(row, index) => row.sourceId ?? `${row.sourceType}-${row.reference ?? "row"}-${index}`}
            emptyMessage={citationSourceId ? "This source record is not in the batch." : "No records match these filters."}
          />
          <Pagination page={page} total={displayData.total} pageSize={pageSize} noun="records" onPageChange={setPage} />
        </CardContent>
      </Card>
    </div>
  );
}

export default TransactionsPage;
