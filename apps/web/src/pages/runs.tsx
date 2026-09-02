import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { PageState, RetryButton } from "@/components/page-state";
import { useRuns } from "@/hooks/use-roborecon";
import { formatDateTime, formatDuration, formatInteger } from "@/lib/format";
import type { RunSummary } from "@/types/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function RunRow({ run }: { run: RunSummary }) {
  return (
    <TableRow>
      <TableCell>
        <Link
          to={`/runs/${run.runId}`}
          className="group inline-flex items-center gap-1.5 font-mono text-sm text-cyan-200 hover:text-cyan-100"
        >
          {run.runId}
          <ArrowUpRight className="size-3 opacity-50 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(run.startedAt)}</p>
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{run.batchId}</TableCell>
      <TableCell>
        <StatusBadge value={run.status} />
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">{formatInteger(run.sourceRowCount)}</TableCell>
      <TableCell className="text-right font-mono tabular-nums">{run.throughput?.toFixed(2) ?? "Unavailable"}</TableCell>
      <TableCell className="font-mono text-xs">{formatDuration(run.durationMs)}</TableCell>
      <TableCell>
        {run.metrics ? (
          <span className={run.metrics.acceptancePassed ? "text-emerald-300" : "text-amber-200"}>
            {run.metrics.acceptancePassed ? "Passed" : "Not passed"}
          </span>
        ) : (
          <span className="text-muted-foreground">Unavailable</span>
        )}
      </TableCell>
    </TableRow>
  );
}

export function RunsPage() {
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const runs = useRuns(page, pageSize);

  if (runs.isLoading) {
    return <PageState kind="loading" headingLevel="h1" title="Loading runs" description="Reading immutable reconciliation run history." />;
  }

  if (runs.isError) {
    return <PageState kind="error" headingLevel="h1" title="Unable to load runs" description={runs.error.message} action={<RetryButton onClick={() => void runs.refetch()} />} />;
  }

  const data = runs.data;
  if (!data) {
    return <PageState kind="error" headingLevel="h1" title="Run data is unavailable" description="The API returned no run history payload." />;
  }

  const total = data.total;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 border-b border-border pb-6 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Runs</h1>
          <p className="mt-2 text-sm text-muted-foreground">Immutable executions of the deterministic policy.</p>
        </div>
        <p className="font-mono text-xs text-muted-foreground">{formatInteger(total)} total runs</p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Run history</CardTitle>
          {runs.isFetching && !runs.isLoading && (
            <span role="status" aria-label="Updating runs" className="text-xs text-cyan-200">
              Updating runs...
            </span>
          )}
        </CardHeader>
        <CardContent>
          {data.items.length === 0 ? (
            <PageState kind="empty" title="No runs yet" description="Reset a demo batch and run reconciliation to create the first evidence-backed run." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Batch</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Records</TableHead>
                    <TableHead className="text-right">Throughput</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Acceptance</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((run) => <RunRow key={run.runId} run={run} />)}
                </TableBody>
              </Table>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
                <span className="text-xs text-muted-foreground">
                  Page {page} of {totalPages} · {formatInteger(total)} runs
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" aria-label="Previous page" disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
                    <ChevronLeft aria-hidden="true" /> Previous
                  </Button>
                  <Button variant="outline" size="sm" aria-label="Next page" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>
                    Next <ChevronRight aria-hidden="true" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default RunsPage;
