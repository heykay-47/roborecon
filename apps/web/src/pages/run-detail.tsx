import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { IconArrowLeft, IconCheck, IconClipboardList, IconX } from "@tabler/icons-react";
import { Alert } from "@/components/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { PageState, RetryButton } from "@/components/page-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAssessBatchClose, useRun } from "@/hooks/use-roborecon";
import { formatDateTime, formatDuration, formatInr, formatInteger, formatPercent } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { BatchCloseBrief, BatchCloseCitation, BatchCloseTheme } from "@/types/api";

function modeLabel(mode: BatchCloseBrief["mode"]): string {
  if (mode === "deterministicFallback") return "Deterministic fallback";
  if (mode === "not required") return "Not required";
  return "Provider";
}

function citationKey(citation: BatchCloseCitation): string {
  return `${citation.exceptionId}:${citation.sourceType ?? ""}:${citation.sourceId ?? ""}`;
}

function BriefCitations({ citations }: { citations: BatchCloseCitation[] }) {
  const uniqueCitations = citations.filter(
    (citation, index) =>
      citations.findIndex((item) => citationKey(item) === citationKey(citation)) === index,
  );

  if (uniqueCitations.length === 0) {
    return <p className="text-sm text-muted-foreground">No citations were returned.</p>;
  }

  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
      {uniqueCitations.map((citation) => (
        <li key={citationKey(citation)}>
          <Link
            to={`/exceptions/${citation.exceptionId}`}
            className="font-mono text-primary underline-offset-4 hover:underline"
          >
            Exception {citation.exceptionId}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function BriefTheme({ theme }: { theme: BatchCloseTheme }) {
  return (
    <article className="rounded-md border border-border bg-muted/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Theme {theme.priority}</p>
          <h3 className="mt-1 text-sm font-semibold text-foreground">{theme.title}</h3>
        </div>
        <p className="font-mono text-sm tabular-nums text-warning">
          {formatInr(theme.moneyExposure)}
        </p>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{theme.summary}</p>
      <dl className="mt-4 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Exceptions</dt>
          <dd className="mt-1 font-mono text-sm tabular-nums">{theme.exceptionCount}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Next action</dt>
          <dd className="mt-1 text-sm text-foreground">{theme.reviewAction}</dd>
        </div>
      </dl>
      <div className="mt-4 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">Cited Exceptions</p>
        <div className="mt-2">
          <BriefCitations citations={theme.citations} />
        </div>
      </div>
    </article>
  );
}

function BatchCloseBriefPanel({ brief }: { brief: BatchCloseBrief }) {
  return (
    <section id="batch-close-brief" aria-labelledby="batch-close-brief-title">
      <Card>
        <CardHeader className="border-b border-border">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Controller assessment</p>
              <CardTitle id="batch-close-brief-title" className="mt-1">
                Batch Close Brief
              </CardTitle>
            </div>
            <StatusBadge value={brief.posture} />
          </div>
          {brief.stale && (
            <p className="text-sm text-warning" role="status">
              Stale after a later Review Decision. Reassess this batch for current guidance.
            </p>
          )}
        </CardHeader>
        <CardContent className="space-y-6">
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Deterministic source rows</dt>
              <dd className="mt-1 font-mono text-lg tabular-nums">
                {formatInteger(brief.deterministicCoverage.sourceRows)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Results assessed</dt>
              <dd className="mt-1 font-mono text-lg tabular-nums">
                {formatInteger(brief.deterministicCoverage.results)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {brief.mode === "provider" ? "Open Exceptions analyzed" : "AI coverage"}
              </dt>
              <dd className="mt-1 font-mono text-lg tabular-nums">
                {formatInteger(brief.aiCoverage.coveredExceptions)} / {formatInteger(brief.aiCoverage.openExceptions)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">AI mode</dt>
              <dd className="mt-1 text-sm font-medium">{modeLabel(brief.mode)}</dd>
            </div>
          </dl>

          <dl className="grid gap-4 border-t border-border pt-5 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Money reconciled</dt>
              <dd className="mt-1 font-mono text-sm text-success">{formatInr(brief.moneyReconciled)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Money unresolved</dt>
              <dd className="mt-1 font-mono text-sm text-warning">{formatInr(brief.moneyUnresolved)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Open Exceptions</dt>
              <dd className="mt-1 font-mono text-sm tabular-nums">{formatInteger(brief.openExceptions)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Financial records changed</dt>
              <dd className="mt-1 font-mono text-sm tabular-nums">{brief.financialRecordsChanged}</dd>
            </div>
          </dl>

          {brief.errorCode && (
            <Alert tone="warning">
              Provider output was not used. Deterministic fallback is shown because {brief.errorMessage ?? brief.errorCode}.
            </Alert>
          )}

          <div>
            <h3 className="text-sm font-semibold text-foreground">Root-cause themes</h3>
            <div className="mt-3 space-y-3">
              {brief.themes.length === 0 ? (
                <p className="text-sm text-muted-foreground">No open Exceptions required synthesis.</p>
              ) : (
                brief.themes.map((theme) => <BriefTheme key={theme.themeId} theme={theme} />)
              )}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-foreground">Next review actions</h3>
            {brief.reviewPlan.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">No manual review actions remain.</p>
            ) : (
              <ol className="mt-3 space-y-3">
                {brief.reviewPlan.map((action) => (
                  <li key={action.priority} className="flex gap-3 text-sm leading-6">
                    <span className="font-mono text-primary">{action.priority}.</span>
                    <div>
                      <p>{action.action}</p>
                      <div className="mt-1">
                        <BriefCitations citations={action.citations} />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="border-t border-border pt-5">
            <h3 className="text-sm font-semibold text-foreground">Citations</h3>
            <div className="mt-3">
              <BriefCitations citations={brief.citations} />
            </div>
          </div>

          <p className="border-t border-border pt-5 text-xs text-muted-foreground">
            Generated {formatDateTime(brief.generatedAt)} by {brief.provider ?? "deterministic policy"}.
            {brief.model ? ` Model ${brief.model}.` : ""} The assessment is read-only: 0 financial records changed.
          </p>
        </CardContent>
      </Card>
    </section>
  );
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const runQuery = useRun(runId);
  const closeBriefMutation = useAssessBatchClose();

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
  const closeBrief = run.closeBrief;
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
          <div className="flex flex-wrap items-center justify-end gap-2">
            {metrics && (
              <div className={`text-sm font-medium ${metrics.acceptancePassed ? "text-success" : "text-warning"}`}>
                {benchmarkStatus}
              </div>
            )}
            {run.status === "completed" && (
              <Button
                type="button"
                size="sm"
                onClick={() => closeBriefMutation.mutate({ runId: run.runId })}
                disabled={closeBriefMutation.isPending}
              >
                <IconClipboardList aria-hidden="true" />
                {closeBriefMutation.isPending
                  ? "Assessing full batch…"
                  : closeBrief?.stale
                    ? "Reassess batch close"
                    : "Assess batch close"}
              </Button>
            )}
          </div>
        }
      />

      {closeBriefMutation.isPending && (
        <Alert role="status">
          Assessing full batch. Checking every persisted source result and Open Exception.
        </Alert>
      )}
      {closeBriefMutation.isError && (
        <Alert tone="danger" role="alert">
          Could not assess batch close. {closeBriefMutation.error.message}
        </Alert>
      )}
      {closeBrief && <BatchCloseBriefPanel brief={closeBrief} />}

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
