import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowLeft, Check, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { PageState, RetryButton } from "@/components/page-state";
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
    <div className="space-y-8">
      <div className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link to="/runs" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden="true" /> Back to runs
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-tight">Run {run.runId}</h1>
            <StatusBadge value={run.status} />
          </div>
          <p className="mt-2 font-mono text-xs text-muted-foreground">Batch {run.batchId} · {formatDateTime(run.completedAt)}</p>
        </div>
        {metrics && (
             <div className={`text-sm font-medium ${metrics.acceptancePassed ? "text-success" : "text-warning"}`}>
            {benchmarkStatus}
          </div>
        )}
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Run summary">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Records checked</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatInteger(run.sourceRowCount)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Throughput</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{run.throughput == null ? "Not available" : `${run.throughput.toFixed(2)} records/s`}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Duration</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatDuration(run.durationMs)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Saved results</p>
          <p className="mt-2 font-mono text-xl tabular-nums">{formatInteger(run.results.length)}</p>
        </div>
      </section>

      {!metrics ? (
        <PageState kind="empty" title="No run metrics" description="This run has no summary report yet." />
      ) : (
        <>
          {metrics.benchmarkAvailable && (
            <p className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
              These scores measure the fixed synthetic demo dataset. They are not production accuracy estimates or guarantees.
            </p>
          )}
          <Card>
            <CardHeader>
              <CardTitle>{metrics.benchmarkAvailable ? "Seeded benchmark checks" : "Run checks"}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(metrics.acceptanceChecks).map(([name, passed]) => (
                  <div key={name} className="flex items-center justify-between gap-4 border-b border-border pb-3">
                    <span className="text-sm text-muted-foreground">{humanizeStatus(name)}</span>
                     <span className={passed ? "inline-flex items-center gap-1 text-sm text-success" : "inline-flex items-center gap-1 text-sm text-danger"}>
                      {passed ? <Check className="size-4" aria-hidden="true" /> : <X className="size-4" aria-hidden="true" />}
                      {passed ? "Passed" : "Failed"}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <section className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
            <Card>
              <CardHeader>
                <CardTitle>{metrics.benchmarkAvailable ? "Seeded benchmark by case type" : "Results by case type"}</CardTitle>
              </CardHeader>
              <CardContent>
                {classes.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Per-class metrics are not available.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[620px] text-sm">
                      <thead className="border-b border-border text-left text-xs uppercase tracking-[0.12em] text-muted-foreground">
                        <tr>
                          <th className="px-2 py-3 font-medium">Case type</th>
                          <th className="px-2 py-3 text-right font-medium">Cases</th>
                          <th className="px-2 py-3 text-right font-medium">Matched</th>
                          <th className="px-2 py-3 text-right font-medium">Match rate</th>
                          <th className="px-2 py-3 text-right font-medium">Precision</th>
                        </tr>
                      </thead>
                      <tbody>
                        {classes.map((metric) => (
                          <tr key={metric.scenarioClass} className="border-b border-border last:border-0">
                            <td className="px-2 py-3 font-medium text-foreground">{humanizeStatus(metric.scenarioClass)}</td>
                            <td className="px-2 py-3 text-right font-mono tabular-nums">{formatInteger(metric.cases)}</td>
                            <td className="px-2 py-3 text-right font-mono tabular-nums">{formatInteger(metric.correctlyResolved)}</td>
                             <td className="px-2 py-3 text-right font-mono tabular-nums text-primary">{formatPercent(metric.matchRate)}</td>
                             <td className="px-2 py-3 text-right font-mono tabular-nums text-success">{formatPercent(metric.precision)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
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
          <CardHeader>
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
                    className="flex scroll-mt-24 flex-col justify-between gap-3 rounded-lg border border-border bg-background/40 p-4 sm:flex-row sm:items-center"
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
