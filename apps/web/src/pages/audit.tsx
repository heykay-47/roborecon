import { useState } from "react";
import type { ComponentProps } from "react";
import { ChevronLeft, ChevronRight, Wrench } from "lucide-react";
import { PageState, RetryButton } from "@/components/page-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useAuditEvents, useBatches, useExceptions, useRuns, type AuditFilters } from "@/hooks/use-roborecon";
import { formatDateTime, formatInteger } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { AuditEvent } from "@/types/api";

const eventTypes = [
  ["", "All events"],
  ["batch.created", "Batch created"],
  ["demo.reset.completed", "Demo reset finished"],
  ["razorpay.sync.started", "Razorpay sync started"],
  ["razorpay.sync.completed", "Razorpay sync finished"],
  ["razorpay.sync.failed", "Razorpay sync failed"],
  ["run.started", "Run started"],
  ["run.completed", "Run completed"],
  ["run.failed", "Run failed"],
  ["result.persisted", "Result saved"],
  ["ai.tool.called", "AI tool used"],
  ["ai.recommendation", "AI suggestion"],
  ["review.approved", "Review approved"],
  ["review.rejected", "Review rejected"],
] as const;

const eventTypeLabels: Record<string, string> = Object.fromEntries(eventTypes);

function chronological(events: AuditEvent[]): AuditEvent[] {
  return [...events].sort((left, right) => {
    const dateDifference = new Date(left.occurredAt).getTime() - new Date(right.occurredAt).getTime();
    return dateDifference || left.sequence - right.sequence || left.eventId.localeCompare(right.eventId);
  });
}

function AuditEventCard({ event }: { event: AuditEvent }) {
  return (
    <article className="relative rounded-lg border border-border bg-background/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-primary">#{event.sequence}</span>
          <span className="text-xs text-muted-foreground">{formatDateTime(event.occurredAt)}</span>
        </div>
        <span className="rounded border border-border px-2 py-1 text-[0.65rem] uppercase tracking-[0.1em] text-muted-foreground">{eventTypeLabels[event.eventType] ?? humanizeStatus(event.eventType)}</span>
      </div>
      <p className="mt-3 break-words text-sm font-medium text-foreground">{event.summary}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>By: <strong className="font-medium text-foreground">{event.actor}</strong></span>
        <span className="break-words">Item: <strong className="break-all font-mono font-normal text-foreground">{event.entityId ?? "Global"}</strong></span>
        {event.sourceId && <span className="break-words">Source: <strong className="break-all font-mono font-normal text-foreground">{event.sourceType ?? "record"} / {event.sourceId}</strong></span>}
      </div>
      {event.toolTrace && (
        <details className="mt-3 border-t border-border/70 pt-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-xs text-muted-foreground"><Wrench className="size-3.5" aria-hidden="true" /> Tool details</summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[0.68rem] leading-5 text-muted-foreground">{JSON.stringify(event.toolTrace, null, 2)}</pre>
        </details>
      )}
    </article>
  );
}

function Pagination({ page, total, pageSize, onPageChange }: { page: number; total: number; pageSize: number; onPageChange: (page: number) => void }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground">Page {page} of {totalPages} · {formatInteger(total)} events</span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" aria-label="Previous page" disabled={page === 1} onClick={() => onPageChange(Math.max(1, page - 1))}><ChevronLeft aria-hidden="true" /> Previous</Button>
        <Button variant="outline" size="sm" aria-label="Next page" disabled={page >= totalPages} onClick={() => onPageChange(Math.min(totalPages, page + 1))}>Next <ChevronRight aria-hidden="true" /></Button>
      </div>
    </div>
  );
}

export function AuditPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Pick<AuditFilters, "batchId" | "runId" | "exceptionId" | "eventType">>({});
  const pageSize = 25;
  const audit = useAuditEvents({ page, pageSize, ...filters });
  const batches = useBatches(1, 50);
  const runs = useRuns(1, 50);
  const exceptions = useExceptions({ page: 1, pageSize: 200 });

  const updateFilter = (name: keyof typeof filters, value: string) => {
    setPage(1);
    setFilters((current) => {
      const next = { ...current, [name]: value || undefined };
      if (name === "runId" && value) next.exceptionId = undefined;
      if (name === "exceptionId" && value) next.runId = undefined;
      return next;
    });
  };

  if (audit.isLoading) return <PageState kind="loading" headingLevel="h1" title="Loading audit history…" description="Getting runs, evidence, AI checks, and review decisions." />;
  if (audit.isError) return <PageState kind="error" headingLevel="h1" title="Could not load audit history" description={audit.error.message} action={<RetryButton onClick={() => void audit.refetch()} />} />;
  if (!audit.data) return <PageState kind="error" headingLevel="h1" title="Audit history is not available" description="No audit history was returned." />;

  const events = chronological(audit.data.items);
  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 border-b border-border pb-6 sm:flex-row sm:items-end">
        <div><h1 className="text-3xl font-semibold tracking-tight">Audit</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">A timeline of runs, evidence, AI checks, and review decisions.</p></div>
        <p className="font-mono text-xs text-muted-foreground">{formatInteger(audit.data.total)} events</p>
      </div>

      <section className="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Audit filters">
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="audit-batch">Batch<Select id="audit-batch" value={filters.batchId ?? ""} onChange={(event) => updateFilter("batchId", event.target.value)}><option value="">All batches</option>{batches.data?.items.map((batch) => <option key={batch.batchId} value={batch.batchId}>{batch.batchId}</option>)}</Select></label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="audit-run">Run<EntitySelect id="audit-run" value={filters.runId ?? ""} onChange={(event) => updateFilter("runId", event.target.value)}><option value="">All runs</option>{runs.data?.items.map((run) => <option key={run.runId} value={run.runId}>{run.runId}</option>)}</EntitySelect></label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="audit-exception">Exception<EntitySelect id="audit-exception" value={filters.exceptionId ?? ""} onChange={(event) => updateFilter("exceptionId", event.target.value)}><option value="">All exceptions</option>{exceptions.data?.items.map((exception) => <option key={exception.exceptionId} value={exception.exceptionId}>{exception.exceptionId}</option>)}</EntitySelect></label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="audit-event-type">Event<Select id="audit-event-type" value={filters.eventType ?? ""} onChange={(event) => updateFilter("eventType", event.target.value)}>{eventTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></label>
      </section>
      <Card>
        <CardHeader className="flex-row items-center justify-between"><CardTitle className="text-sm font-medium">Event history</CardTitle>{audit.isFetching && !audit.isLoading && <span role="status" className="text-xs text-primary">Updating history…</span>}</CardHeader>
        <CardContent>
          {events.length === 0 ? <PageState kind="empty" title="No events match these filters." description="Events appear after a reset, run, investigation, or review." /> : <div className="space-y-3">{events.map((event) => <AuditEventCard key={event.eventId} event={event} />)}<Pagination page={audit.data.page} total={audit.data.total} pageSize={pageSize} onPageChange={setPage} /></div>}
        </CardContent>
      </Card>
    </div>
  );
}

function EntitySelect(props: ComponentProps<typeof Select>) {
  return <Select {...props} />;
}

export default AuditPage;
