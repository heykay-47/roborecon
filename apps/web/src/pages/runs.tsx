import { useState } from "react";
import { Link } from "react-router-dom";
import { IconArrowUpRight } from "@tabler/icons-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
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
  const benchmarkStatus = !run.metrics?.benchmarkAvailable
    ? "Not scored"
    : run.metrics.acceptancePassed
      ? "Benchmark passed"
      : "Benchmark not met";

  return (
    <TableRow>
      <TableCell>
        <Link
          to={`/runs/${run.runId}`}
           className="group inline-flex items-center gap-1.5 font-mono text-sm text-primary hover:text-primary/80"
        >
          {run.runId}
           <IconArrowUpRight className="size-3 opacity-50 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(run.startedAt)}</p>
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{run.batchId}</TableCell>
      <TableCell>
        <StatusBadge value={run.status} />
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">{formatInteger(run.sourceRowCount)}</TableCell>
           <TableCell className="text-right font-mono tabular-nums">{run.throughput?.toFixed(2) ?? "Not available"}</TableCell>
      <TableCell className="font-mono text-xs">{formatDuration(run.durationMs)}</TableCell>
      <TableCell>
        {run.metrics ? (
           <span className={run.metrics.acceptancePassed ? "text-success" : "text-warning"}>
             {benchmarkStatus}
          </span>
        ) : (
           <span className="text-muted-foreground">Not available</span>
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
    return <PageState kind="loading" headingLevel="h1" title="Loading run history…" description="Getting saved reconciliation runs." />;
  }

  if (runs.isError) {
    return <PageState kind="error" headingLevel="h1" title="Could not load run history" description={runs.error.message} action={<RetryButton onClick={() => void runs.refetch()} />} />;
  }

  const data = runs.data;
  if (!data) {
    return <PageState kind="error" headingLevel="h1" title="Run history is not available" description="No run history was returned." />;
  }

  const total = data.total;

  return (
    <div className="page-stack">
      <PageHeader
        title="Runs"
        description="Saved Reconciliation Runs from each batch."
        actions={<p className="font-mono text-xs text-muted-foreground">{formatInteger(total)} saved runs</p>}
      />

      <Card className="gap-0 py-0">
        <CardHeader className="panel-header">
          <CardTitle className="text-sm font-medium">Saved runs</CardTitle>
          {runs.isFetching && !runs.isLoading && (
              <span role="status" aria-label="Updating run list…" className="text-xs text-primary">
              Updating run list…
            </span>
          )}
        </CardHeader>
        <CardContent className={data.items.length === 0 ? "p-4" : "p-0"}>
          {data.items.length === 0 ? (
            <PageState kind="empty" title="No runs yet" description="Reset the demo data, then run reconciliation to create the first run." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Batch</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Records</TableHead>
                    <TableHead className="text-right">Speed</TableHead>
                    <TableHead>Time</TableHead>
                    <TableHead>Checks</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((run) => <RunRow key={run.runId} run={run} />)}
                </TableBody>
              </Table>
              <Pagination page={page} total={total} pageSize={pageSize} noun="saved runs" onPageChange={setPage} />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default RunsPage;
