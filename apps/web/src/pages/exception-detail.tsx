import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, CircleAlert, X } from "lucide-react";
import {
  CandidateEvidence,
  CriterionEvidenceList,
  InvestigationTrace,
  RecordSummary,
  ScoreSummary,
  ToolTrace,
} from "@/components/evidence";
import { PageState, RetryButton } from "@/components/page-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useException, useInvestigate, useReviewException } from "@/hooks/use-roborecon";
import { ApiError } from "@/lib/api";
import { valueToText } from "@/lib/evidence";
import { formatDateTime, formatInr } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { AIInvestigation, ExceptionDetail, ReviewAction } from "@/types/api";

function sourceValues(source: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(source).filter(([key]) => key !== "sourceType"));
}

function sourceId(source: Record<string, unknown>): string | null {
  const value = source.sourceId ?? source.id;
  return typeof value === "string" ? value : null;
}

function findSource(sources: Record<string, unknown>[], id: string): Record<string, unknown> | undefined {
  return sources.find((source) => sourceId(source) === id);
}

function formatAge(createdAt: string | null | undefined): string {
  if (!createdAt) return "Age unavailable";
  const timestamp = new Date(createdAt).getTime();
  if (Number.isNaN(timestamp)) return "Age unavailable";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function sourceTypeFor(source: Record<string, unknown>): string | null {
  return typeof source.sourceType === "string" ? source.sourceType : null;
}

function Arithmetic({ arithmetic }: { arithmetic: Record<string, unknown> }) {
  const entries = Object.entries(arithmetic).filter(([key]) => key !== "observations");
  const observations = Array.isArray(arithmetic.observations) ? arithmetic.observations : [];
  if (entries.length === 0 && observations.length === 0) {
    return <p className="text-sm text-muted-foreground">No arithmetic observations were persisted.</p>;
  }

  return (
    <div className="space-y-3">
      <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt className="text-xs text-muted-foreground">{humanizeStatus(key)}</dt>
            <dd className="mt-1 break-words font-mono text-sm tabular-nums">{valueToText(value)}</dd>
          </div>
        ))}
      </dl>
      {observations.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground">Observed arithmetic inputs</p>
          <div className="mt-2 space-y-2">
            {observations.map((observation, index) => (
              <pre key={index} className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-background/40 p-3 font-mono text-xs leading-5 text-muted-foreground">
                {valueToText(observation)}
              </pre>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewActions({ exception, onRefresh }: { exception: ExceptionDetail; onRefresh: () => Promise<unknown> }) {
  const review = useReviewException();
  const [pendingAction, setPendingAction] = useState<ReviewAction | null>(null);
  const [candidateId, setCandidateId] = useState<string>("");
  const [note, setNote] = useState("");
  const result = exception.result;
  const candidates = result?.candidates ?? [];
  const isOpen = exception.status === "open";
  const error = review.error;
  const conflict = error instanceof ApiError && error.status === 409;

  const refresh = async () => {
    review.reset();
    setPendingAction(null);
    await onRefresh();
  };

  if (!isOpen) {
    return (
      <div className="rounded-lg border border-border bg-background/30 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground"><Check className="size-4 text-emerald-300" aria-hidden="true" /> Terminal review recorded</div>
        <p className="mt-2 text-sm text-muted-foreground">This exception is {humanizeStatus(exception.status)} and cannot be reviewed again.</p>
        {exception.reviewNote && <p className="mt-3 text-sm leading-6 text-foreground">{exception.reviewNote}</p>}
      </div>
    );
  }

  const chooseAction = (action: ReviewAction) => {
    setPendingAction(action);
    review.reset();
  };
  const confirm = () => {
    if (!pendingAction) return;
    review.mutate({
      exceptionId: exception.exceptionId,
      action: pendingAction,
      candidateId: pendingAction === "approve" ? candidateId || undefined : undefined,
      note: note || undefined,
    });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-300/20 bg-amber-300/5 p-4">
        <p className="text-sm font-medium text-amber-100">Human review is terminal</p>
        <p className="mt-1 text-sm leading-6 text-amber-100/80">Approve creates a non-autonomous human link. Reject records Confirmed No-Match while the money remains financially unresolved.</p>
      </div>
      {candidates.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium">Candidate for approval</legend>
          <div className="mt-2 space-y-2">
            {candidates.map((candidate) => (
              <label key={candidate.candidateId} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-background/30 p-3 has-[:checked]:border-cyan-300/60 has-[:checked]:bg-cyan-300/5">
                <input type="radio" name="candidate" value={candidate.candidateId} checked={candidateId === candidate.candidateId} onChange={() => setCandidateId(candidate.candidateId)} className="mt-1 accent-cyan-300" />
                <span className="min-w-0 flex-1"><span className="block break-all font-mono text-xs text-foreground">{candidate.candidateId}</span><span className="mt-1 block text-xs text-muted-foreground">Score {candidate.score} · {candidate.exactIdentifierChain ? "Exact identifier chain" : "Candidate evidence only"}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <label className="block text-sm font-medium" htmlFor="review-note">
        Note <span className="font-normal text-muted-foreground">(optional)</span>
        <Textarea id="review-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Record the evidence used for this decision." className="mt-2 min-h-24" maxLength={4000} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="default" disabled={candidates.length === 0} onClick={() => chooseAction("approve")}><Check aria-hidden="true" /> Approve candidate</Button>
        <Button type="button" variant="destructive" onClick={() => chooseAction("reject")}><X aria-hidden="true" /> Reject as no-match</Button>
      </div>
      {pendingAction && (
        <div className="rounded-lg border border-cyan-300/30 bg-cyan-300/5 p-4" role="region" aria-label="Review confirmation">
          <p className="text-sm font-medium">Confirm {pendingAction === "approve" ? "approval" : "rejection"}?</p>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">This action is terminal and will be written to the audit trail. It cannot be undone from this workspace.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={confirm} disabled={review.isPending || (pendingAction === "approve" && !candidateId)}>{review.isPending ? "Saving review..." : `Confirm ${pendingAction}`}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setPendingAction(null)} disabled={review.isPending}>Cancel</Button>
          </div>
        </div>
      )}
      {review.isSuccess && <p className="text-sm text-emerald-300" role="status">Review recorded. Refreshing the exception state.</p>}
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-300/30 bg-rose-300/5 p-3 text-sm text-rose-200" role="alert">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-3">
            <span className="block">{conflict ? "This exception was reviewed elsewhere. Refresh before making another decision." : error.message}</span>
            {conflict && <Button type="button" size="sm" variant="outline" onClick={() => void refresh()}>Refresh exception</Button>}
          </div>
        </div>
      )}
    </div>
  );
}

function InvestigationAction({ exception }: { exception: ExceptionDetail }) {
  const investigation = useInvestigate();
  if (exception.status !== "open") return null;

  return (
    <div className="border-b border-border pb-4">
      <Button
        type="button"
        variant="outline"
        onClick={() => investigation.mutate({ exceptionId: exception.exceptionId })}
        disabled={investigation.isPending}
      >
        {investigation.isPending
          ? "Investigating..."
          : exception.aiReady
            ? "Investigate exception"
            : "Run another investigation"}
      </Button>
      {investigation.isSuccess && (
        <p className="mt-2 text-xs text-emerald-300" role="status">
          Advisory investigation recorded. Refreshing the trace.
        </p>
      )}
      {investigation.isError && (
        <p className="mt-2 text-xs text-rose-200" role="alert">
          Investigation failed: {investigation.error.message}
        </p>
      )}
    </div>
  );
}

function ExceptionContent({ exception, onRefresh }: { exception: ExceptionDetail; onRefresh: () => Promise<unknown> }) {
  const result = exception.result;
  const primary = exception.sourceId ? findSource(exception.sourceSummaries, exception.sourceId) : undefined;
  const candidates = result?.candidates ?? [];
  const candidateSources = candidates.map((candidate) => ({ candidate, source: findSource(exception.sourceSummaries, candidate.candidateId) }));
  const investigationRecords = exception.aiInvestigations;

  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-6">
        <Link to="/exceptions" className="mb-4 inline-flex min-h-8 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" aria-hidden="true" /> Back to exceptions</Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 break-all text-2xl font-semibold tracking-tight sm:text-3xl">Exception {exception.exceptionId}</h1>
          <StatusBadge value={exception.status} />
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{humanizeStatus(exception.exceptionType)} · {humanizeStatus(exception.sourceType ?? "unknown source")}</p>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Exception summary">
        {[
          ["Amount", formatInr(exception.amount)],
          ["Class", humanizeStatus(exception.exceptionType)],
          ["Age", formatAge(exception.createdAt)],
          ["Status", humanizeStatus(exception.status)],
          ["AI readiness", investigationRecords.length > 0 ? "Trace available" : "No trace returned"],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border bg-card p-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 break-words font-mono text-sm tabular-nums text-foreground">{value}</p>
          </div>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Review context</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              <p className="break-words rounded-lg border border-amber-400/20 bg-amber-400/5 p-4 text-sm leading-6 text-amber-100">{exception.message}</p>
              <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Primary source</dt><dd className="mt-1 break-all font-mono text-sm">{exception.sourceId ?? "No canonical ID"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Related run</dt><dd className="mt-1 text-sm">{exception.runId ? <Link className="break-all text-cyan-200 hover:text-cyan-100" to={`/runs/${exception.runId}`}>Run {exception.runId}</Link> : "None"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Related result</dt><dd className="mt-1 text-sm">{exception.runId && exception.resultId ? <Link className="break-all text-cyan-200 hover:text-cyan-100" to={`/runs/${exception.runId}#result-${exception.resultId}`}>Result {exception.resultId}</Link> : "None"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Reviewed by</dt><dd className="mt-1 text-sm">{exception.reviewedBy ?? "Not reviewed"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Reviewed at</dt><dd className="mt-1 text-sm">{formatDateTime(exception.reviewedAt)}</dd></div>
              </dl>
              {exception.reviewNote && <div className="border-t border-border pt-4"><p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Review note</p><p className="mt-2 text-sm leading-6">{exception.reviewNote}</p></div>}
            </CardContent>
          </Card>

          <section aria-labelledby="records-heading">
            <div className="mb-3"><h2 id="records-heading" className="text-lg font-semibold">Primary and candidate records</h2><p className="mt-1 text-sm text-muted-foreground">Source rows are shown as returned by the batch. No hidden truth is used.</p></div>
            <div className="grid gap-4 lg:grid-cols-2">
              {primary ? <RecordSummary title="Primary record" sourceType={sourceTypeFor(primary)} sourceId={sourceId(primary)} values={sourceValues(primary)} /> : <RecordSummary title="Primary record" sourceType={exception.sourceType} sourceId={exception.sourceId} values={{ message: "Primary source summary unavailable" }} />}
              <div className="space-y-3">
                {candidateSources.length > 0 ? candidateSources.map(({ candidate, source }) => source ? <RecordSummary key={candidate.candidateId} title="Candidate record" sourceType={sourceTypeFor(source)} sourceId={sourceId(source)} values={sourceValues(source)} /> : <CandidateEvidence key={candidate.candidateId} candidate={candidate} />) : <RecordSummary title="Candidate records" values={{ message: "No ranked candidates were returned" }} />}
              </div>
            </div>
          </section>

          <Card>
            <CardHeader><CardTitle>Deterministic score and evidence</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              {result ? <ScoreSummary score={result.score} runnerUpScore={result.runnerUpScore} margin={result.margin} autonomous={result.autonomous} /> : <p className="text-sm text-muted-foreground">No reconciliation result is linked to this exception.</p>}
              <div><h3 className="mb-3 text-sm font-medium">Criterion evidence</h3><CriterionEvidenceList evidence={exception.criterionEvidence} /></div>
              {result && result.candidates.length > 0 && <div><h3 className="mb-3 text-sm font-medium">Ranked candidates</h3><div className="space-y-2">{result.candidates.map((candidate) => <CandidateEvidence key={candidate.candidateId} candidate={candidate} />)}</div></div>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Settlement calculation</CardTitle></CardHeader>
            <CardContent><Arithmetic arithmetic={exception.arithmetic} /></CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>AI advisory trace</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <InvestigationAction exception={exception} />
              {investigationRecords.length > 0 ? investigationRecords.map((investigation: AIInvestigation) => <InvestigationTrace key={investigation.investigationId} investigation={investigation} />) : <p className="text-sm text-muted-foreground">No AI investigation was persisted for this exception. Deterministic evidence remains authoritative.</p>}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-6 xl:sticky xl:top-24 xl:self-start">
          <Card>
            <CardHeader><CardTitle>Terminal review</CardTitle></CardHeader>
            <CardContent><ReviewActions exception={exception} onRefresh={onRefresh} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Audit chronology</CardTitle></CardHeader>
            <CardContent>
              {exception.auditEvents.length > 0 ? <ol className="space-y-4">{exception.auditEvents.map((event) => <li key={event.eventId} className="relative border-l border-border pl-4"><p className="font-mono text-xs text-cyan-200">#{event.sequence} · {formatDateTime(event.occurredAt)}</p><p className="mt-1 text-sm font-medium">{event.summary}</p><p className="mt-1 text-xs text-muted-foreground">{event.actor} · {humanizeStatus(event.eventType)}</p>{event.toolTrace && <ToolTrace trace={[event.toolTrace]} />}</li>)}</ol> : <p className="text-sm text-muted-foreground">No exception-scoped audit events returned.</p>}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}

export function ExceptionDetailPage() {
  const { exceptionId } = useParams<{ exceptionId: string }>();
  const exceptionQuery = useException(exceptionId);

  if (exceptionQuery.isLoading) return <PageState kind="loading" headingLevel="h1" title="Loading exception" description="Reading the exception evidence and review history." />;
  if (exceptionQuery.isError) {
    if (exceptionQuery.error instanceof ApiError && exceptionQuery.error.status === 404) {
      return <PageState kind="empty" headingLevel="h1" title="Exception not found" description="The requested exception is no longer available in this workspace." />;
    }
    if (exceptionQuery.error instanceof ApiError && exceptionQuery.error.status === 409) {
      return <PageState kind="error" headingLevel="h1" title="Exception state conflict" description="The exception state changed while it was loading. Refresh before continuing." action={<RetryButton onClick={() => void exceptionQuery.refetch()} />} />;
    }
    return <PageState kind="error" headingLevel="h1" title="Unable to load exception" description={exceptionQuery.error.message} action={<RetryButton onClick={() => void exceptionQuery.refetch()} />} />;
  }
  if (!exceptionQuery.data) return <PageState kind="empty" headingLevel="h1" title="Exception not found" description="The requested exception is not available." />;
  return <ExceptionContent exception={exceptionQuery.data} onRefresh={() => exceptionQuery.refetch()} />;
}

export default ExceptionDetailPage;
