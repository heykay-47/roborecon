import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { IconAlertCircle, IconArrowLeft, IconCheck, IconX } from "@tabler/icons-react";
import { Alert } from "@/components/alert";
import {
  CandidateEvidence,
  CriterionEvidenceList,
  InvestigationTrace,
  RecordSummary,
  ScoreSummary,
  ToolTrace,
} from "@/components/evidence";
import { PageState, RetryButton } from "@/components/page-state";
import { PageHeader } from "@/components/page-header";
import { Timeline, TimelineItem } from "@/components/timeline";
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
  if (!createdAt) return "Unknown";
  const timestamp = new Date(createdAt).getTime();
  if (Number.isNaN(timestamp)) return "Unknown";
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
    return <p className="text-sm text-muted-foreground">No settlement calculation was saved.</p>;
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
          <p className="text-xs text-muted-foreground">Values used in the calculation</p>
          <div className="mt-2 space-y-2">
            {observations.map((observation, index) => (
               <pre key={index} className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-muted/35 p-3 font-mono text-xs leading-5 text-muted-foreground">
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
      <div className="rounded-md border border-border bg-muted/20 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground"><IconCheck className="size-4 text-success" aria-hidden="true" /> Review complete</div>
        <p className="mt-2 text-sm text-muted-foreground">This exception is {humanizeStatus(exception.status)} and cannot be changed.</p>
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
         <Alert tone="warning">
          <p className="text-sm font-medium text-warning">This decision cannot be undone</p>
          <p className="mt-1 text-sm leading-6 text-warning">Approve creates a human-approved link, not an automatic match. Reject marks it Confirmed No-Match. The money stays unresolved.</p>
        </Alert>
      {candidates.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium">Choose a candidate to approve</legend>
          <div className="mt-2 space-y-2">
            {candidates.map((candidate) => (
               <label key={candidate.candidateId} className="flex cursor-pointer items-start gap-3 rounded-md border border-border bg-muted/20 p-3 has-[:checked]:border-primary/60 has-[:checked]:bg-primary/5">
                 <input type="radio" name="candidate" value={candidate.candidateId} checked={candidateId === candidate.candidateId} onChange={() => setCandidateId(candidate.candidateId)} className="mt-1 accent-primary" />
                <span className="min-w-0 flex-1"><span className="block break-all font-mono text-xs text-foreground">{candidate.candidateId}</span><span className="mt-1 block text-xs text-muted-foreground">Score {candidate.score} · {candidate.exactIdentifierChain ? "Exact ID match" : "Evidence only"}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <label className="block text-sm font-medium" htmlFor="review-note">
         Review note <span className="font-normal text-muted-foreground">(optional)</span>
         <Textarea id="review-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add the evidence behind this decision." className="mt-2 min-h-24" maxLength={4000} />
      </label>
      <div className="flex flex-wrap gap-2">
          <Button type="button" variant="default" disabled={candidates.length === 0} onClick={() => chooseAction("approve")}><IconCheck aria-hidden="true" /> Approve this match</Button>
          <Button type="button" variant="destructive" onClick={() => chooseAction("reject")}><IconX aria-hidden="true" /> Reject: no match</Button>
      </div>
      {pendingAction && (
           <div className="rounded-md border border-primary/30 bg-primary/8 p-4" role="region" aria-label="Confirm review decision">
          <p className="text-sm font-medium">Confirm {pendingAction === "approve" ? "approval" : "rejection"}?</p>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">This decision is final. It will be added to the audit history and cannot be undone here.</p>
          <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={confirm} disabled={review.isPending || (pendingAction === "approve" && !candidateId)}>{review.isPending ? "Saving decision…" : `Confirm ${pendingAction === "approve" ? "approval" : "rejection"}`}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setPendingAction(null)} disabled={review.isPending}>Cancel</Button>
          </div>
        </div>
      )}
       {review.isSuccess && <p className="text-sm text-success" role="status">Decision saved. Refreshing the exception.</p>}
       {error && (
         <Alert tone="danger">
           <div className="flex items-start gap-2 text-danger">
             <IconAlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
             <div className="space-y-3">
               <span className="block">{conflict ? "This exception was reviewed elsewhere. Refresh before deciding again." : error.message}</span>
               {conflict && <Button type="button" size="sm" variant="outline" onClick={() => void refresh()}>Refresh exception</Button>}
             </div>
           </div>
         </Alert>
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
          ? "Checking evidence…"
          : exception.aiReady
            ? "Investigate exception"
            : "Run another check"}
      </Button>
      {investigation.isSuccess && (
          <p className="mt-2 text-xs text-success" role="status">
          Investigation saved. Refreshing the evidence.
        </p>
      )}
      {investigation.isError && (
          <p className="mt-2 text-xs text-danger" role="alert">
          Could not investigate exception: {investigation.error.message}
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
    <div className="page-stack">
      <PageHeader
        title={`Exception ${exception.exceptionId}`}
        backLink={<Link to="/exceptions" className="mb-3 inline-flex min-h-8 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><IconArrowLeft className="size-4" aria-hidden="true" /> Back to exceptions</Link>}
        status={<StatusBadge value={exception.status} />}
        description={`${humanizeStatus(exception.exceptionType)} · ${humanizeStatus(exception.sourceType ?? "unknown source")}`}
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Exception summary">
        {[
          ["Amount", formatInr(exception.amount)],
          ["Class", humanizeStatus(exception.exceptionType)],
          ["Age", formatAge(exception.createdAt)],
          ["Status", humanizeStatus(exception.status)],
          ["Investigation", investigationRecords.length > 0 ? "Investigation saved" : "No investigation yet"],
        ].map(([label, value]) => (
          <div key={label} className="panel p-3">
            <p className="eyebrow">{label}</p>
            <p className="mt-1 break-words font-mono text-sm tabular-nums text-foreground">{value}</p>
          </div>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader className="border-b border-border"><CardTitle>Issue details</CardTitle></CardHeader>
            <CardContent className="space-y-5">
               <Alert tone="warning" className="text-warning">{exception.message}</Alert>
              <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                  <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Main record</dt><dd className="mt-1 break-all font-mono text-sm">{exception.sourceId ?? "No record ID"}</dd></div>
                  <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Run</dt><dd className="mt-1 text-sm">{exception.runId ? <Link className="break-all text-primary hover:text-primary/80" to={`/runs/${exception.runId}`}>Run {exception.runId}</Link> : "None"}</dd></div>
                  <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Result</dt><dd className="mt-1 text-sm">{exception.runId && exception.resultId ? <Link className="break-all text-primary hover:text-primary/80" to={`/runs/${exception.runId}#result-${exception.resultId}`}>Result {exception.resultId}</Link> : "None"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Reviewed by</dt><dd className="mt-1 text-sm">{exception.reviewedBy ?? "Not reviewed"}</dd></div>
                <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Reviewed at</dt><dd className="mt-1 text-sm">{formatDateTime(exception.reviewedAt)}</dd></div>
              </dl>
              {exception.reviewNote && <div className="border-t border-border pt-4"><p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Review note</p><p className="mt-2 text-sm leading-6">{exception.reviewNote}</p></div>}
            </CardContent>
          </Card>

          <section aria-labelledby="records-heading">
            <div className="mb-3"><h2 id="records-heading" className="text-lg font-semibold">Main record and possible matches</h2><p className="mt-1 text-sm text-muted-foreground">Only source rows are shown. Hidden test answers are not used.</p></div>
            <div className="grid gap-4 lg:grid-cols-2">
              {primary ? <RecordSummary title="Main record" sourceType={sourceTypeFor(primary)} sourceId={sourceId(primary)} values={sourceValues(primary)} /> : <RecordSummary title="Main record" sourceType={exception.sourceType} sourceId={exception.sourceId} values={{ message: "Main record details are not available" }} />}
              <div className="space-y-3">
                {candidateSources.length > 0 ? candidateSources.map(({ candidate, source }) => source ? <RecordSummary key={candidate.candidateId} title="Possible match" sourceType={sourceTypeFor(source)} sourceId={sourceId(source)} values={sourceValues(source)} /> : <CandidateEvidence key={candidate.candidateId} candidate={candidate} />) : <RecordSummary title="Possible matches" values={{ message: "No possible matches were found" }} />}
              </div>
            </div>
          </section>

          <Card>
            <CardHeader className="border-b border-border"><CardTitle>Match score and evidence</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              {result ? <ScoreSummary score={result.score} runnerUpScore={result.runnerUpScore} margin={result.margin} autonomous={result.autonomous} /> : <p className="text-sm text-muted-foreground">No match result is linked to this exception.</p>}
              <div><h3 className="mb-3 text-sm font-medium">Why this score</h3><CriterionEvidenceList evidence={exception.criterionEvidence} /></div>
              {result && result.candidates.length > 0 && <div><h3 className="mb-3 text-sm font-medium">Possible matches</h3><div className="space-y-2">{result.candidates.map((candidate) => <CandidateEvidence key={candidate.candidateId} candidate={candidate} />)}</div></div>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border"><CardTitle>Settlement calculation</CardTitle></CardHeader>
            <CardContent><Arithmetic arithmetic={exception.arithmetic} /></CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border"><CardTitle>AI investigation</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <InvestigationAction exception={exception} />
              {investigationRecords.length > 0 ? investigationRecords.map((investigation: AIInvestigation) => <InvestigationTrace key={investigation.investigationId} investigation={investigation} />) : <p className="text-sm text-muted-foreground">No AI investigation is saved. The matching evidence is still the source of truth.</p>}
            </CardContent>
          </Card>
        </div>

         <aside aria-label="Review tools" className="space-y-6 xl:sticky xl:top-24 xl:self-start">
           <Card>
             <CardHeader className="border-b border-border"><CardTitle>Review decision</CardTitle></CardHeader>
            <CardContent><ReviewActions exception={exception} onRefresh={onRefresh} /></CardContent>
          </Card>
           <Card>
             <CardHeader className="border-b border-border"><CardTitle>Audit history</CardTitle></CardHeader>
            <CardContent>
                {exception.auditEvents.length > 0 ? <Timeline>{exception.auditEvents.map((event) => <TimelineItem key={event.eventId}><p className="font-mono text-xs text-primary">#{event.sequence} · {formatDateTime(event.occurredAt)}</p><p className="mt-1 text-sm font-medium">{event.summary}</p><p className="mt-1 text-xs text-muted-foreground">{event.actor} · {humanizeStatus(event.eventType)}</p>{event.toolTrace && <ToolTrace trace={[event.toolTrace]} />}</TimelineItem>)}</Timeline> : <p className="text-sm text-muted-foreground">No audit events for this exception.</p>}
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

  if (exceptionQuery.isLoading) return <PageState kind="loading" headingLevel="h1" title="Loading exception…" description="Getting the evidence and review history." />;
  if (exceptionQuery.isError) {
    if (exceptionQuery.error instanceof ApiError && exceptionQuery.error.status === 404) {
      return <PageState kind="empty" headingLevel="h1" title="Exception not found" description="This exception is no longer available." />;
    }
    if (exceptionQuery.error instanceof ApiError && exceptionQuery.error.status === 409) {
      return <PageState kind="error" headingLevel="h1" title="Exception changed" description="This exception changed while loading. Refresh before deciding." action={<RetryButton onClick={() => void exceptionQuery.refetch()} />} />;
    }
    return <PageState kind="error" headingLevel="h1" title="Could not load exception" description={exceptionQuery.error.message} action={<RetryButton onClick={() => void exceptionQuery.refetch()} />} />;
  }
  if (!exceptionQuery.data) return <PageState kind="empty" headingLevel="h1" title="Exception not found" description="This exception is not available." />;
  return <ExceptionContent exception={exceptionQuery.data} onRefresh={() => exceptionQuery.refetch()} />;
}

export default ExceptionDetailPage;
