import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { PageState, RetryButton } from "@/components/page-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
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
  ["", "All exception types"],
  ["ambiguous", "Ambiguous"],
  ["duplicate", "Duplicate"],
  ["missing_razorpay", "Missing Razorpay"],
  ["missing_ledger", "Missing ledger"],
  ["missing_settlement", "Missing settlement"],
  ["missing_bank_credit", "Missing bank credit"],
  ["amount_mismatch", "Amount mismatch"],
  ["malformed", "Malformed"],
] as const;

function ExceptionIdentity({ exception }: { exception: ExceptionSummary }) {
  return (
    <div className="min-w-0">
      <Link
        to={`/exceptions/${exception.exceptionId}`}
        className="group inline-flex max-w-full items-center gap-1.5 font-mono text-sm text-cyan-200 hover:text-cyan-100"
      >
        <span className="truncate">Exception {exception.exceptionId}</span>
        <ArrowUpRight className="size-3 shrink-0 opacity-60 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
      </Link>
      <p className="mt-1 break-words text-xs text-muted-foreground">{exception.message}</p>
    </div>
  );
}

function ExceptionRow({ exception }: { exception: ExceptionSummary }) {
  return (
    <tr className="border-b border-border/70 last:border-0">
      <td className="px-4 py-3 align-top"><ExceptionIdentity exception={exception} /></td>
      <td className="px-4 py-3 align-top">
        <p className="text-sm font-medium">{humanizeStatus(exception.exceptionType)}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{humanizeStatus(exception.sourceType ?? "unknown source")}</p>
      </td>
      <td className="px-4 py-3 align-top font-mono text-sm tabular-nums">{formatInr(exception.amount)}</td>
      <td className="px-4 py-3 align-top text-sm text-muted-foreground">{exception.createdAt ? formatDateTime(exception.createdAt) : "Age unavailable"}</td>
      <td className="px-4 py-3 align-top"><StatusBadge value={exception.status} /></td>
      <td className="px-4 py-3 align-top text-xs text-muted-foreground">{exception.aiReady ? "Ready to investigate" : "Trace recorded or closed"}</td>
    </tr>
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
          <dt className="text-xs text-muted-foreground">Class</dt>
          <dd className="mt-1 font-medium">{humanizeStatus(exception.exceptionType)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Amount</dt>
          <dd className="mt-1 font-mono tabular-nums">{formatInr(exception.amount)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Age</dt>
          <dd className="mt-1 text-muted-foreground">{exception.createdAt ? formatDateTime(exception.createdAt) : "Age unavailable"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">AI readiness</dt>
          <dd className="mt-1 text-muted-foreground">{exception.aiReady ? "Ready to investigate" : "Trace recorded or closed"}</dd>
        </div>
      </dl>
    </article>
  );
}

function Pagination({ page, total, pageSize, onPageChange }: { page: number; total: number; pageSize: number; onPageChange: (page: number) => void }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground">Page {page} of {totalPages} · {formatInteger(total)} exceptions</span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" aria-label="Previous page" disabled={page === 1} onClick={() => onPageChange(Math.max(1, page - 1))}>
          <ChevronLeft aria-hidden="true" /> Previous
        </Button>
        <Button variant="outline" size="sm" aria-label="Next page" disabled={page >= totalPages} onClick={() => onPageChange(Math.min(totalPages, page + 1))}>
          Next <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </div>
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
    return <PageState kind="loading" headingLevel="h1" title="Loading exceptions" description="Reading unresolved reconciliation cases and their review state." />;
  }
  if (exceptions.isError) {
    return <PageState kind="error" headingLevel="h1" title="Unable to load exceptions" description={exceptions.error.message} action={<RetryButton onClick={() => void exceptions.refetch()} />} />;
  }

  const data = exceptions.data;
  if (!data) {
    return <PageState kind="error" headingLevel="h1" title="Exception data is unavailable" description="The API returned no exception queue payload." />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 border-b border-border pb-6 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Exceptions</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Review uncertainty without hiding the evidence that caused it.</p>
        </div>
        <p className="font-mono text-xs text-muted-foreground">{formatInteger(data.total)} total cases</p>
      </div>

      <section className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Exception filters">
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="exception-status">
          Exception status
          <Select id="exception-status" value={filters.status ?? ""} onChange={(event) => updateFilter("status", event.target.value)}>
            {statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="exception-batch">
          Batch
          <Select id="exception-batch" value={filters.batchId ?? ""} onChange={(event) => updateFilter("batchId", event.target.value)} disabled={batches.isLoading}>
            <option value="">All batches</option>
            {batches.data?.items.map((batch) => <option key={batch.batchId} value={batch.batchId}>{batch.batchId} · {batch.kind}</option>)}
          </Select>
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="exception-type">
          Exception type
          <Select id="exception-type" value={filters.exceptionType ?? ""} onChange={(event) => updateFilter("exceptionType", event.target.value)}>
            {exceptionTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="exception-run">
          Reconciliation run
          <Select id="exception-run" value={filters.runId ?? ""} onChange={(event) => updateFilter("runId", event.target.value)} disabled={runs.isLoading}>
            <option value="">All runs</option>
            {runs.data?.items.map((run) => <option key={run.runId} value={run.runId}>{run.runId}</option>)}
          </Select>
        </label>
      </section>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Review queue</CardTitle>
          {exceptions.isFetching && !exceptions.isLoading && <span role="status" className="text-xs text-cyan-200">Updating exceptions...</span>}
        </CardHeader>
        <CardContent>
          {data.items.length === 0 ? (
            <PageState kind="empty" title="No exceptions match these filters." description="Try another status or batch, or run reconciliation to create new evidence." />
          ) : (
            <>
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead className="border-b border-border text-xs uppercase tracking-[0.12em] text-muted-foreground">
                    <tr>
                      <th className="px-4 pb-3 font-medium">Exception</th>
                      <th className="px-4 pb-3 font-medium">Class</th>
                      <th className="px-4 pb-3 font-medium">Amount</th>
                      <th className="px-4 pb-3 font-medium">Age</th>
                      <th className="px-4 pb-3 font-medium">Status</th>
                      <th className="px-4 pb-3 font-medium">AI readiness</th>
                    </tr>
                  </thead>
                  <tbody>{data.items.map((exception) => <ExceptionRow key={exception.exceptionId} exception={exception} />)}</tbody>
                </table>
              </div>
              <div className="md:hidden">
                {data.items.map((exception) => <ExceptionCard key={exception.exceptionId} exception={exception} />)}
              </div>
              <div className="mt-4"><Pagination page={page} total={data.total} pageSize={pageSize} onPageChange={setPage} /></div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default ExceptionsPage;
