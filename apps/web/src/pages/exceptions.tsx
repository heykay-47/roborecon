import { useState } from "react";
import { Link } from "react-router-dom";
import { IconArrowUpRight } from "@tabler/icons-react";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { PageState, RetryButton } from "@/components/page-state";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useBatches, useExceptions, useRuns, type ExceptionFilters } from "@/hooks/use-roborecon";
import { formatDateTime, formatInr, formatInteger } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { ExceptionSummary } from "@/types/api";

const statuses = [
  ["", "All statuses"],
  ["open", "Open"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
] as const;

const exceptionTypes = [
  ["", "All issue types"],
  ["ambiguous", "Ambiguous"],
  ["duplicate", "Duplicate"],
  ["missing_razorpay", "Missing Razorpay"],
  ["missing_ledger", "Missing ledger"],
  ["missing_settlement", "Missing settlement"],
  ["missing_bank_credit", "Missing bank credit"],
  ["amount_mismatch", "Amount mismatch"],
  ["malformed", "Invalid record"],
] as const;

function ExceptionIdentity({ exception }: { exception: ExceptionSummary }) {
  return (
    <div className="min-w-0">
      <Link
        to={`/exceptions/${exception.exceptionId}`}
         className="group inline-flex max-w-full items-center gap-1.5 font-mono text-sm text-primary hover:text-primary/80"
      >
        <span className="truncate">Exception {exception.exceptionId}</span>
         <IconArrowUpRight className="size-3 shrink-0 opacity-60 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
      </Link>
      <p className="mt-1 break-words text-xs text-muted-foreground">{exception.message}</p>
    </div>
  );
}

function ExceptionRow({ exception }: { exception: ExceptionSummary }) {
  return (
    <TableRow>
      <TableCell className="align-top"><ExceptionIdentity exception={exception} /></TableCell>
      <TableCell className="align-top">
        <p className="text-sm font-medium">{humanizeStatus(exception.exceptionType)}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{humanizeStatus(exception.sourceType ?? "unknown source")}</p>
      </TableCell>
      <TableCell className="align-top font-mono text-sm tabular-nums">{formatInr(exception.amount)}</TableCell>
      <TableCell className="align-top text-sm text-muted-foreground">{exception.createdAt ? formatDateTime(exception.createdAt) : "Unknown"}</TableCell>
      <TableCell className="align-top"><StatusBadge value={exception.status} /></TableCell>
      <TableCell className="align-top text-xs text-muted-foreground">{exception.aiReady ? "Ready to investigate" : "Already investigated or closed"}</TableCell>
    </TableRow>
  );
}

function ExceptionCard({ exception }: { exception: ExceptionSummary }) {
  return (
    <article className="border-b border-border/70 p-4 last:border-0">
      <div className="flex items-start justify-between gap-3">
        <ExceptionIdentity exception={exception} />
        <StatusBadge value={exception.status} />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Type</dt>
          <dd className="mt-1 font-medium">{humanizeStatus(exception.exceptionType)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Amount</dt>
          <dd className="mt-1 font-mono tabular-nums">{formatInr(exception.amount)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Age</dt>
          <dd className="mt-1 text-muted-foreground">{exception.createdAt ? formatDateTime(exception.createdAt) : "Unknown"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Investigation</dt>
          <dd className="mt-1 text-muted-foreground">{exception.aiReady ? "Ready to investigate" : "Already investigated or closed"}</dd>
        </div>
      </dl>
    </article>
  );
}

export function ExceptionsPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Pick<ExceptionFilters, "batchId" | "runId" | "exceptionType" | "status">>({});
  const pageSize = 25;
  const exceptions = useExceptions({ page, pageSize, ...filters });
  const batches = useBatches(1, 50);
  const runs = useRuns(1, 50);

  const updateFilter = (name: keyof typeof filters, value: string) => {
    setPage(1);
    setFilters((current) => ({ ...current, [name]: value || undefined }));
  };

  if (exceptions.isLoading) {
    return <PageState kind="loading" headingLevel="h1" title="Loading exceptions…" description="Getting cases that need review." />;
  }
  if (exceptions.isError) {
    return <PageState kind="error" headingLevel="h1" title="Could not load exceptions" description={exceptions.error.message} action={<RetryButton onClick={() => void exceptions.refetch()} />} />;
  }

  const data = exceptions.data;
  if (!data) {
    return <PageState kind="error" headingLevel="h1" title="Exceptions are not available" description="No exception data was returned." />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Exceptions"
        description="Review unclear matches with the evidence behind them."
        actions={<p className="font-mono text-xs text-muted-foreground">{formatInteger(data.total)} total cases</p>}
      />

      <section className="filter-panel grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Exception filters">
        <label className="field-label" htmlFor="exception-status">
          Status
          <Select id="exception-status" value={filters.status ?? ""} onChange={(event) => updateFilter("status", event.target.value)}>
            {statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="field-label" htmlFor="exception-batch">
          Batch
          <Select id="exception-batch" value={filters.batchId ?? ""} onChange={(event) => updateFilter("batchId", event.target.value)} disabled={batches.isLoading}>
            <option value="">All batches</option>
            {batches.data?.items.map((batch) => <option key={batch.batchId} value={batch.batchId}>{batch.batchId} · {batch.kind}</option>)}
          </Select>
        </label>
        <label className="field-label" htmlFor="exception-type">
          Issue type
          <Select id="exception-type" value={filters.exceptionType ?? ""} onChange={(event) => updateFilter("exceptionType", event.target.value)}>
            {exceptionTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="field-label" htmlFor="exception-run">
          Run
          <Select id="exception-run" value={filters.runId ?? ""} onChange={(event) => updateFilter("runId", event.target.value)} disabled={runs.isLoading}>
            <option value="">All runs</option>
            {runs.data?.items.map((run) => <option key={run.runId} value={run.runId}>{run.runId}</option>)}
          </Select>
        </label>
      </section>

      <Card className="gap-0 py-0">
        <CardHeader className="panel-header">
          <CardTitle className="text-sm font-medium">Exceptions to review</CardTitle>
            {exceptions.isFetching && !exceptions.isLoading && <span role="status" className="text-xs text-primary">Updating list…</span>}
        </CardHeader>
        <CardContent className={data.items.length === 0 ? "p-4" : "p-0"}>
          {data.items.length === 0 ? (
              <PageState kind="empty" title="No exceptions match these filters." description="Try different filters, or run reconciliation to find new exceptions." />
          ) : (
            <>
              <div className="hidden md:block">
                <Table className="min-w-[860px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Exception</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Amount</TableHead>
                      <TableHead>Age</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Investigation</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>{data.items.map((exception) => <ExceptionRow key={exception.exceptionId} exception={exception} />)}</TableBody>
                </Table>
              </div>
              <div className="md:hidden">
                {data.items.map((exception) => <ExceptionCard key={exception.exceptionId} exception={exception} />)}
              </div>
              <Pagination page={page} total={data.total} pageSize={pageSize} noun="exceptions" onPageChange={setPage} />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default ExceptionsPage;
