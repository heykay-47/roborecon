import { lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert } from "@/components/alert";
import { MetricCard } from "@/components/metric-card";
import { PageState, RetryButton } from "@/components/page-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  useOverview,
  useResetDemo,
  useRunReconciliation,
} from "@/hooks/use-roborecon";
import {
  formatDateTime,
  formatDecimal,
  formatDuration,
  formatInr,
  formatInteger,
  formatPercent,
} from "@/lib/format";
import type { BatchStatus } from "@/types/api";

const OverviewChart = lazy(() => import("@/components/overview-chart"));

const chartLoadingState = (
  <div className="flex h-full items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
    Loading chart…
  </div>
);

const chartUnavailableState = (
  <div className="flex h-full items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
    The chart is not available in this browser.
  </div>
);

function OverviewActions({
  batchId,
  batchStatus,
  onReset,
  onRun,
  isResetting,
  isRunning,
}: {
  batchId: string | undefined;
  batchStatus: BatchStatus | undefined;
  onReset: () => void;
  onRun: () => void;
  isResetting: boolean;
  isRunning: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onClick={onReset} disabled={isResetting || isRunning}>
        {isResetting ? "Resetting demo data…" : "Reset demo data"}
      </Button>
      <Button
        size="sm"
        onClick={onRun}
        disabled={!batchId || batchStatus !== "completed" || isResetting || isRunning}
      >
        {isRunning ? "Running reconciliation…" : "Run reconciliation"}
      </Button>
    </div>
  );
}

export function OverviewPage() {
  const navigate = useNavigate();
  const overview = useOverview();
  const resetMutation = useResetDemo();
  const runMutation = useRunReconciliation();
  const activeBatch = resetMutation.data ?? overview.data?.latestBatch ?? null;

  const reset = () => {
    if (resetMutation.isPending || runMutation.isPending) return;
    if (window.confirm("Reset the demo data? Current demo records will be replaced.")) {
      resetMutation.mutate();
    }
  };

  const run = () => {
    if (!activeBatch) return;
    runMutation.mutate(activeBatch.batchId, {
      onSuccess: (result) => navigate(`/runs/${result.runId}`),
    });
  };

  if (overview.isLoading) {
    return (
      <PageState
        kind="loading"
        headingLevel="h1"
         title="Loading summary…"
        description="Getting the latest batch and run results."
      />
    );
  }

  if (overview.isError) {
    return (
      <PageState
        kind="error"
        headingLevel="h1"
        title="Could not load summary"
        description={overview.error.message}
        action={<RetryButton onClick={() => void overview.refetch()} />}
      />
    );
  }

  const data = overview.data;
  if (!data) {
    return (
      <PageState
        kind="error"
        headingLevel="h1"
        title="Summary is not available"
        description="No summary data was returned."
      />
    );
  }

  const metrics = data.metrics;

  if (!metrics) {
    return (
      <div className="page-stack">
        <PageHeader
          title="Overview"
          description="See the latest results, evidence, and items that need review."
          actions={
            <OverviewActions
            batchId={activeBatch?.batchId}
            batchStatus={activeBatch?.status}
            onReset={reset}
            onRun={run}
            isResetting={resetMutation.isPending}
            isRunning={runMutation.isPending}
            />
          }
        />
        <PageState
          kind="empty"
           title="No completed run yet"
          description={
            activeBatch
               ? `Batch ${activeBatch.batchId} is ready. Run reconciliation to see the results and evidence.`
               : "Reset the demo data, then run reconciliation to see the results."
          }
        />
        {resetMutation.isError && <Alert tone="danger">Could not reset demo data: {resetMutation.error.message}</Alert>}
        {runMutation.isError && <Alert tone="danger">Could not run reconciliation: {runMutation.error.message}</Alert>}
      </div>
    );
  }

  const scenarios = Object.values(metrics.perClass ?? {});

  return (
    <div className="page-stack">
      <PageHeader
        title="Overview"
        description="See the latest results, evidence, and items that need review."
        status={
          <Badge
            variant="outline"
            className={
              metrics.benchmarkAvailable
                 ? "border-success/30 bg-success/10 text-success"
                 : "border-warning/30 bg-warning/10 text-warning"
            }
          >
            {metrics.benchmarkAvailable ? "Seeded benchmark available" : "Benchmark unavailable"}
          </Badge>
        }
        actions={
          <>
            {activeBatch && <StatusBadge value={activeBatch.status} />}
            <OverviewActions
            batchId={activeBatch?.batchId}
            batchStatus={activeBatch?.status}
            onReset={reset}
            onRun={run}
            isResetting={resetMutation.isPending}
            isRunning={runMutation.isPending}
            />
          </>
        }
      />

      {resetMutation.isError && <Alert tone="danger">Could not reset demo data: {resetMutation.error.message}</Alert>}
      {runMutation.isError && <Alert tone="danger">Could not run reconciliation: {runMutation.error.message}</Alert>}

      {metrics.benchmarkAvailable && (
        <Alert tone="warning">
            These scores measure the fixed synthetic demo dataset. They are not production accuracy estimates or guarantees.
        </Alert>
      )}

      <section className="panel grid sm:grid-cols-2 xl:grid-cols-5" aria-label="Run summary">
        <MetricCard
          label="Benchmark match rate"
          value={formatPercent(metrics.matchRate)}
           detail={`${formatInteger(metrics.correctlyResolved)} of ${formatInteger(metrics.matchableCases)} cases matched`}
          tone="positive"
        />
        <MetricCard
          label="Benchmark precision"
          value={formatPercent(metrics.precision)}
           detail={`${formatInteger(metrics.falsePositives)} incorrect matches`}
          tone={metrics.falsePositives === 0 ? "positive" : "warning"}
        />
        <MetricCard
            label="End-to-end autonomous resolution"
          value={formatPercent(metrics.endToEndAutonomyRate)}
            detail={`${formatInteger(metrics.autonomousCases)} cases resolved automatically`}
        />
        <MetricCard
           label="Needs review"
          value={formatInteger(metrics.openExceptions)}
           detail={`${formatInteger(metrics.financiallyUnresolvedCases)} cases still unresolved`}
          tone={metrics.openExceptions === 0 ? "positive" : "warning"}
        />
        <MetricCard
           label="Records checked"
          value={formatInteger(metrics.recordsProcessed)}
           detail={`${formatDuration(metrics.durationMs)} to check them`}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
        <div className="panel p-4 sm:p-5">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
            <div>
                <h2 className="text-base font-semibold">{metrics.benchmarkAvailable ? "Seeded benchmark by case type" : "Results by case type"}</h2>
               <p className="mt-1 text-sm text-muted-foreground">
                  {metrics.benchmarkAvailable ? "Scores against hidden truth in the fixed synthetic dataset." : "Operational outcomes from this Reconciliation Run."}
              </p>
            </div>
            {metrics.runId && (
              <Button variant="link" size="sm" onClick={() => navigate(`/runs/${metrics.runId}`)}>
                 View run
              </Button>
            )}
          </div>
          {scenarios.length === 0 ? (
            <div className="mt-6 rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
               No case-type results are available for this run.
            </div>
          ) : (
            <div className="mt-6 h-64 w-full">
              {typeof ResizeObserver === "undefined" ? (
                chartUnavailableState
              ) : (
                <Suspense fallback={chartLoadingState}>
                  <OverviewChart scenarios={scenarios} />
                </Suspense>
              )}
            </div>
          )}
        </div>

        <div className="panel p-4 sm:p-5">
          <h2 className="text-base font-semibold">Money summary</h2>
          <p className="mt-1 text-sm text-muted-foreground">Amounts are shown in INR.</p>
          <dl className="mt-6 divide-y divide-border">
            <div className="flex items-baseline justify-between gap-4 py-3 first:pt-0">
               <dt className="text-sm text-muted-foreground">Money reconciled</dt>
               <dd className="font-mono text-sm font-semibold tabular-nums text-success">{formatInr(metrics.moneyReconciled)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3">
               <dt className="text-sm text-muted-foreground">Money unresolved</dt>
               <dd className="font-mono text-sm font-semibold tabular-nums text-warning">{formatInr(metrics.moneyUnresolved)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3">
              <dt className="text-sm text-muted-foreground">Net settlement</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums">{formatInr(metrics.settlementNet)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3 last:pb-0">
              <dt className="text-sm text-muted-foreground">Speed</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums">{formatDecimal(metrics.throughput)} records/s</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="panel p-4">
          <p className="eyebrow">Current batch</p>
          <p className="mt-2 font-mono text-sm text-foreground">{activeBatch?.batchId ?? "No batch"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {activeBatch?.seed ?? "No demo batch yet"} · {formatDateTime(activeBatch?.completedAt)}
          </p>
        </div>
        <div className="panel p-4">
          <p className="eyebrow">Run ID</p>
          <p className="mt-2 font-mono text-sm text-foreground">{metrics.runId}</p>
          <p className="mt-1 text-sm text-muted-foreground">
             Report version {metrics.reportVersion} · {metrics.acceptancePassed ? "checks passed" : "checks not met"}
          </p>
        </div>
      </section>
    </div>
  );
}

export default OverviewPage;
