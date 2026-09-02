import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/metric-card";
import { PageState, RetryButton } from "@/components/page-state";
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
import { humanizeStatus } from "@/lib/status-colors";
import type { BatchStatus } from "@/types/api";

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
        {isResetting ? "Resetting demo..." : "Reset demo"}
      </Button>
      <Button
        size="sm"
        onClick={onRun}
        disabled={!batchId || batchStatus !== "completed" || isResetting || isRunning}
      >
        {isRunning ? "Running reconciliation..." : "Run reconciliation"}
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
    if (window.confirm("Reset the demo batch? Existing demo records will be replaced.")) {
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
        title="Loading overview"
        description="Reading the latest batch and completed run metrics."
      />
    );
  }

  if (overview.isError) {
    return (
      <PageState
        kind="error"
        headingLevel="h1"
        title="Unable to load overview"
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
        title="Overview data is unavailable"
        description="The API returned no overview payload."
      />
    );
  }

  const metrics = data.metrics;

  if (!metrics) {
    return (
      <div className="space-y-8">
        <div className="flex flex-col justify-between gap-4 border-b border-border pb-6 sm:flex-row sm:items-end">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Overview</h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              The control plane for deterministic payment reconciliation.
            </p>
          </div>
          <OverviewActions
            batchId={activeBatch?.batchId}
            batchStatus={activeBatch?.status}
            onReset={reset}
            onRun={run}
            isResetting={resetMutation.isPending}
            isRunning={runMutation.isPending}
          />
        </div>
        <PageState
          kind="empty"
          title="No completed reconciliation yet"
          description={
            activeBatch
              ? `Batch ${activeBatch.batchId} is ready. Run the deterministic policy to generate evidence and metrics.`
              : "Reset the seeded demo to create a reviewable batch, then run reconciliation."
          }
        />
        {resetMutation.isError && (
          <p className="text-sm text-rose-200" role="alert">
            Demo reset failed: {resetMutation.error.message}
          </p>
        )}
        {runMutation.isError && (
          <p className="text-sm text-rose-200" role="alert">
            Reconciliation failed: {runMutation.error.message}
          </p>
        )}
      </div>
    );
  }

  const scenarios = Object.values(metrics.perClass ?? {});

  return (
    <div className="space-y-8">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-6 xl:flex-row xl:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Overview</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            One run, one evidence trail, and a clear boundary between autonomous matches and review.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Badge
            variant="outline"
            className={
              metrics.benchmarkAvailable
                ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
                : "border-amber-400/30 bg-amber-400/10 text-amber-200"
            }
          >
            {metrics.benchmarkAvailable ? "Benchmark available" : "Benchmark unavailable"}
          </Badge>
          {activeBatch && <StatusBadge value={activeBatch.status} />}
          <OverviewActions
            batchId={activeBatch?.batchId}
            batchStatus={activeBatch?.status}
            onReset={reset}
            onRun={run}
            isResetting={resetMutation.isPending}
            isRunning={runMutation.isPending}
          />
        </div>
      </div>

      {resetMutation.isError && (
        <p className="text-sm text-rose-200" role="alert">
          Demo reset failed: {resetMutation.error.message}
        </p>
      )}
      {runMutation.isError && (
        <p className="text-sm text-rose-200" role="alert">
          Reconciliation failed: {runMutation.error.message}
        </p>
      )}

      <section className="grid overflow-hidden rounded-xl border border-border bg-card sm:grid-cols-2 xl:grid-cols-5" aria-label="Run metrics">
        <MetricCard
          label="Match rate"
          value={formatPercent(metrics.matchRate)}
          detail={`${formatInteger(metrics.correctlyResolved)} of ${formatInteger(metrics.matchableCases)} matchable cases`}
          tone="positive"
        />
        <MetricCard
          label="Precision"
          value={formatPercent(metrics.precision)}
          detail={`${formatInteger(metrics.falsePositives)} false positives`}
          tone={metrics.falsePositives === 0 ? "positive" : "warning"}
        />
        <MetricCard
          label="Autonomous rate"
          value={formatPercent(metrics.endToEndAutonomyRate)}
          detail={`${formatInteger(metrics.autonomousCases)} autonomous cases`}
        />
        <MetricCard
          label="Open exceptions"
          value={formatInteger(metrics.openExceptions)}
          detail={`${formatInteger(metrics.financiallyUnresolvedCases)} financially unresolved`}
          tone={metrics.openExceptions === 0 ? "positive" : "warning"}
        />
        <MetricCard
          label="Records processed"
          value={formatInteger(metrics.recordsProcessed)}
          detail={`${formatDuration(metrics.durationMs)} deterministic duration`}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
            <div>
              <h2 className="text-base font-semibold">Scenario performance</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Per-class match rate and precision from the persisted evaluation report.
              </p>
            </div>
            {metrics.runId && (
              <Button variant="link" size="sm" onClick={() => navigate(`/runs/${metrics.runId}`)}>
                Open run
              </Button>
            )}
          </div>
          {scenarios.length === 0 ? (
            <div className="mt-6 rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              Scenario metrics are not available for this batch.
            </div>
          ) : (
            <div className="mt-6 h-64 w-full">
              {typeof ResizeObserver === "undefined" ? (
                <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                  Scenario chart requires a measurable browser viewport.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scenarios} margin={{ top: 8, right: 8, left: -18, bottom: 8 }}>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />
                    <XAxis
                      dataKey="scenarioClass"
                      tickFormatter={humanizeStatus}
                      tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tickFormatter={(value: number) => `${value}%`}
                      tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(96, 215, 231, 0.06)" }}
                      contentStyle={{
                        background: "#0d1b2b",
                        border: "1px solid #1a344b",
                        borderRadius: "8px",
                        color: "#e8f0f7",
                      }}
                      formatter={(value) => [formatPercent(typeof value === "number" ? value : null), "Rate"]}
                      labelFormatter={(label) => humanizeStatus(String(label))}
                    />
                    <Bar dataKey="matchRate" name="Match rate" fill="#60d7e7" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="precision" name="Precision" fill="#6ee7a0" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-base font-semibold">Money position</h2>
          <p className="mt-1 text-sm text-muted-foreground">Values reported in integer INR paise.</p>
          <dl className="mt-6 divide-y divide-border">
            <div className="flex items-baseline justify-between gap-4 py-3 first:pt-0">
              <dt className="text-sm text-muted-foreground">Money reconciled</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums text-emerald-300">{formatInr(metrics.moneyReconciled)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3">
              <dt className="text-sm text-muted-foreground">Money unresolved</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums text-amber-200">{formatInr(metrics.moneyUnresolved)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3">
              <dt className="text-sm text-muted-foreground">Settlement net</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums">{formatInr(metrics.settlementNet)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 py-3 last:pb-0">
              <dt className="text-sm text-muted-foreground">Throughput</dt>
              <dd className="font-mono text-sm font-semibold tabular-nums">{formatDecimal(metrics.throughput)} records/s</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="grid gap-4 border-t border-border pt-6 sm:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Current batch</p>
          <p className="mt-2 font-mono text-sm text-foreground">{activeBatch?.batchId ?? "Not available"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {activeBatch?.seed ?? "No seeded batch has been created"} · {formatDateTime(activeBatch?.completedAt)}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Run identity</p>
          <p className="mt-2 font-mono text-sm text-foreground">{metrics.runId}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Report version {metrics.reportVersion} · {metrics.acceptancePassed ? "acceptance passed" : "acceptance not passed"}
          </p>
        </div>
      </section>
    </div>
  );
}

export default OverviewPage;
