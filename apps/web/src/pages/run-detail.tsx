import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { IconArrowLeft, IconCheck, IconX } from "@tabler/icons-react";
import { Alert } from "@/components/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { PageState, RetryButton } from "@/components/page-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRun } from "@/hooks/use-roborecon";
import { formatDateTime, formatDuration, formatInr, formatInteger, formatPercent } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const runQuery = useRun(runId);

  useEffect(() => {
    if (!runQuery.data || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [location.hash, runQuery.data]);

  if (runQuery.isLoading) {
    return <PageState kind="loading" headingLevel="h1" title="Loading run details…" description="Getting results, links, and checks." />;
  }

  if (runQuery.isError) {
    return <PageState kind="error" headingLevel="h1" title="Could not load run" description={runQuery.error.message} action={<RetryButton onClick={() => void runQuery.refetch()} />} />;
  }

  if (!runQuery.data) {
    return <PageState kind="empty" headingLevel="h1" title="Run not found" description="This run is not available." />;
  }

  const run = runQuery.data;
  const metrics = run.metrics;
  const classes = Object.values(metrics?.perClass ?? {});
  const benchmarkStatus = !metrics?.benchmarkAvailable
    ? "Benchmark unavailable"
    : metrics.acceptancePassed
      ? "Seeded benchmark passed"
      : "Seeded benchmark not met";

  return (
    <div className="page-stack">
      <PageHeader
        title={`Run ${run.runId}`}
        backLink={
          <Link to="/runs" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <IconArrowLeft className="size-4" aria-hidden="true" /> Back to runs
          </Link>
        }
        status={<StatusBadge value={run.status} />}
        description={<span className="font-mono text-xs">Batch {run.batchId} · {formatDateTime(run.completedAt)}</span>}
        actions={
          metrics && (
            <div className={`text-sm font-medium ${metrics.acceptancePassed ? "text-success" : "text-warning"}`}>
              {benchmarkStatus}
            </div>
          )
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Run summary">
        <div className="panel p-4">
          <p className="eyebrow">Records checked</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatInteger(run.sourceRowCount)}</p>
        </div>
        <div className="panel p-4">
          <p className="eyebrow">Throughput</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{run.throughput == null ? "Not available" : `${run.throughput.toFixed(2)} records/s`}</p>
        </div>
        <div className="panel p-4">
          <p className="eyebrow">Duration</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatDuration(run.durationMs)}</p>
        </div>
        <div className="panel p-4">
          <p className="eyebrow">Saved results</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatInteger(run.results.length)}</p>
        </div>
      </section>

      {!metrics ? (
        <PageState kind="empty" title="No run metrics" description="This run has no summary report yet." />
      ) : (
        <>
          {metrics.benchmarkAvailable && (
            <Alert tone="warning">
               These scores measure the fixed synthetic demo dataset. They are not production accuracy estimates or guarantees.
            </Alert>
          )}
          <Card className="gap-0 py-0">
            <CardHeader className="panel-header">
              <CardTitle>{metrics.benchmarkAvailable ? "Seeded benchmark checks" : "Run checks"}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(metrics.acceptanceChecks).map(([name, passed]) => (
                  <div key={name} className="flex items-center justify-between gap-4 border-b border-border pb-3">
                    <span className="text-sm text-muted-foreground">{humanizeStatus(name)}</span>
                     <span className={passed ? "inline-flex items-center gap-1 text-sm text-success" : "inline-flex items-center gap-1 text-sm text-danger"}>
                      {passed ? <IconCheck className="size-4" aria-hidden="true" /> : <IconX className="size-4" aria-hidden="true" />}
                      {passed ? "Passed" : "Failed"}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <section className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
            <Card>
              <CardHeader className="border-b border-border">
                <CardTitle>{metrics.benchmarkAvailable ? "Seeded benchmark by case type" : "Results by case type"}</CardTitle>
              </CardHeader>
              <CardContent>
                {classes.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Per-class metrics are not available.</p>
                ) : (
                  <Table className="min-w-[620px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Case type</TableHead>
                        <TableHead className="text-right">Cases</TableHead>
                        <TableHead className="text-right">Matched</TableHead>
                        <TableHead className="text-right">Match rate</TableHead>
                        <TableHead className="text-right">Precision</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                        {classes.map((metric) => (
                          <TableRow key={metric.scenarioClass}>
                            <TableCell className="font-medium text-foreground">{humanizeStatus(metric.scenarioClass)}</TableCell>
                            <TableCell className="text-right font-mono tabular-nums">{formatInteger(metric.cases)}</TableCell>
                            <TableCell className="text-right font-mono tabular-nums">{formatInteger(metric.correctlyResolved)}</TableCell>
                             <TableCell className="text-right font-mono tabular-nums text-primary">{formatPercent(metric.matchRate)}</TableCell>
                             <TableCell className="text-right font-mono tabular-nums text-success">{formatPercent(metric.precision)}</TableCell>
                          </TableRow>
                        ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="border-b border-border">
                <CardTitle>Money and review</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="divide-y divide-border">
                   <div className="flex items-baseline justify-between gap-3 py-3 first:pt-0"><dt className="text-sm text-muted-foreground">Money reconciled</dt><dd className="font-mono text-sm text-success">{formatInr(metrics.moneyReconciled)}</dd></div>
                   <div className="flex items-baseline justify-between gap-3 py-3"><dt className="text-sm text-muted-foreground">Money unresolved</dt><dd className="font-mono text-sm text-warning">{formatInr(metrics.moneyUnresolved)}</dd></div>
                  <div className="flex items-baseline justify-between gap-3 py-3"><dt className="text-sm text-muted-foreground">Needs review</dt><dd className="font-mono text-sm">{formatInteger(metrics.openExceptions)}</dd></div>
                  <div className="flex items-baseline justify-between gap-3 py-3 last:pb-0"><dt className="text-sm text-muted-foreground">Net settlement</dt><dd className="font-mono text-sm">{formatInr(metrics.settlementNet)}</dd></div>
                </dl>
              </CardContent>
            </Card>
          </section>
        </>
      )}

      <section aria-label="Persisted results">
        <Card>
          <CardHeader className="border-b border-border">
            <CardTitle>Saved results</CardTitle>
          </CardHeader>
          <CardContent>
            {run.results.length === 0 ? (
              <p className="text-sm text-muted-foreground">No saved results are linked to this run.</p>
            ) : (
              <div className="space-y-3">
                {run.results.map((result) => (
                  <article
                    key={result.resultId}
                    id={`result-${result.resultId}`}
                    className="flex scroll-mt-24 flex-col justify-between gap-3 rounded-md border border-border bg-muted/20 p-4 sm:flex-row sm:items-center"
                  >
                    <div>
                       <p className="font-mono text-sm text-primary">{result.resultId}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {humanizeStatus(result.stage)} · {result.selectedIds.length} selected source records
                      </p>
                    </div>
                    <StatusBadge value={result.status} />
                  </article>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

export default RunDetailPage;
