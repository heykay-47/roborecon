import { ExternalLink, Wrench } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isRecord, valueToText } from "@/lib/evidence";
import { humanizeStatus } from "@/lib/status-colors";
import type { AIInvestigation, CopilotCitation, CriterionEvidence, ScoredCandidate } from "@/types/api";

function citationHref(sourceType: string, sourceId: string): string {
  return `/transactions?source=${encodeURIComponent(sourceType)}&sourceId=${encodeURIComponent(sourceId)}`;
}

export function RecordSummary({
  title,
  sourceType,
  sourceId,
  values,
}: {
  title: string;
  sourceType?: string | null;
  sourceId?: string | null;
  values: Record<string, unknown>;
}) {
  const fields = Object.entries(values).filter(([key]) => key !== "id" && key !== "sourceType");

  return (
    <Card size="sm" className="h-full bg-background/40">
      <CardHeader className="border-b border-border/80">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{title}</span>
          {sourceType && <Badge variant="outline">{humanizeStatus(sourceType)}</Badge>}
        </CardTitle>
        <p className="break-all font-mono text-[0.7rem] text-muted-foreground">
          {sourceId ?? "No canonical ID"}
        </p>
      </CardHeader>
      <CardContent>
        {fields.length > 0 ? (
          <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
            {fields.map(([key, value]) => (
              <div key={key} className="min-w-0">
                <dt className="text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {humanizeStatus(key)}
                </dt>
                <dd className="mt-1 break-words font-mono text-xs leading-5 text-foreground">
                  {valueToText(value)}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">No source fields were returned.</p>
        )}
      </CardContent>
    </Card>
  );
}

export function CandidateEvidence({ candidate }: { candidate: ScoredCandidate }) {
  return (
    <div className="rounded-lg border border-border bg-background/30 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">Candidate</p>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{candidate.candidateId}</p>
        </div>
        <div className="text-right font-mono tabular-nums">
          <p className="text-lg font-semibold text-cyan-200">{candidate.score}</p>
          <p className="text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">score</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[0.68rem]">
        {candidate.exactIdentifierChain && <Badge variant="outline" className="text-emerald-200">Exact chain</Badge>}
        {candidate.verifiedSettlementMath && <Badge variant="outline" className="text-emerald-200">Math verified</Badge>}
        {candidate.duplicate && <Badge variant="outline" className="text-rose-200">Duplicate</Badge>}
      </div>
      {candidate.contradictions.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-rose-200">
          {candidate.contradictions.map((contradiction) => <li key={contradiction}>{contradiction}</li>)}
        </ul>
      )}
    </div>
  );
}

export function CriterionEvidenceList({ evidence }: { evidence: CriterionEvidence[] }) {
  if (evidence.length === 0) {
    return <p className="text-sm text-muted-foreground">No criterion evidence was persisted.</p>;
  }

  return (
    <div className="space-y-2">
      {evidence.map((item, index) => (
        <div key={`${item.ruleCode}-${index}`} className="grid gap-2 rounded-lg border border-border bg-background/30 p-3 md:grid-cols-[9rem_5rem_1fr] md:items-start">
          <div>
            <p className="font-mono text-xs font-semibold text-cyan-200">{item.ruleCode}</p>
            <p className="mt-1 text-xs text-muted-foreground">{humanizeStatus(item.result)}</p>
          </div>
          <p className="font-mono text-sm tabular-nums text-foreground">{item.points > 0 ? `+${item.points}` : item.points} pts</p>
          <div>
            <p className="text-sm leading-5 text-foreground">{item.explanation}</p>
            <p className="mt-2 break-words font-mono text-[0.7rem] leading-5 text-muted-foreground">
              Observed: {valueToText(item.observedValues)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ScoreSummary({
  score,
  runnerUpScore,
  margin,
  autonomous,
}: Pick<ScoredCandidate, "score"> & { runnerUpScore: number; margin: number; autonomous: boolean }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-4">
      <div className="rounded-lg border border-border bg-background/30 p-3">
        <dt className="text-xs text-muted-foreground">Top score</dt>
        <dd className="mt-1 font-mono text-xl font-semibold tabular-nums text-cyan-200">{score}</dd>
      </div>
      <div className="rounded-lg border border-border bg-background/30 p-3">
        <dt className="text-xs text-muted-foreground">Runner-up</dt>
        <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">{runnerUpScore}</dd>
      </div>
      <div className="rounded-lg border border-border bg-background/30 p-3">
        <dt className="text-xs text-muted-foreground">Margin</dt>
        <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">{margin}</dd>
      </div>
      <div className="rounded-lg border border-border bg-background/30 p-3">
        <dt className="text-xs text-muted-foreground">Policy authority</dt>
        <dd className={autonomous ? "mt-1 text-sm font-medium text-emerald-300" : "mt-1 text-sm font-medium text-amber-200"}>
          {autonomous ? "Autonomous" : "Review required"}
        </dd>
      </div>
    </dl>
  );
}

export function InvestigationTrace({ investigation }: { investigation: AIInvestigation }) {
  return (
    <div className="rounded-lg border border-border bg-background/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">Advisory investigation</h3>
            <Badge variant="outline" className={investigation.mode === "deterministicFallback" ? "text-amber-200" : "text-cyan-200"}>
              {investigation.mode === "deterministicFallback" ? "Deterministic fallback" : humanizeStatus(investigation.mode)}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {investigation.provider ?? "No provider"}{investigation.model ? ` · ${investigation.model}` : ""} · confidence {investigation.confidence}%
          </p>
        </div>
        {investigation.errorCode && <span className="text-xs text-rose-200">{investigation.errorCode}</span>}
      </div>
      <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-foreground">{investigation.recommendation}</p>
      <CitationList citations={investigation.citations} />
      <ToolTrace trace={investigation.toolTrace} />
      {investigation.errorMessage && <p className="mt-3 text-xs text-rose-200">{investigation.errorMessage}</p>}
    </div>
  );
}

export function CitationList({ citations }: { citations: CopilotCitation[] | Record<string, unknown>[] }) {
  const normalized = citations.flatMap((citation) => {
    if (!isRecord(citation)) return [];
    const sourceType = typeof citation.sourceType === "string" ? citation.sourceType : null;
    const sourceId = typeof citation.sourceId === "string" ? citation.sourceId : null;
    return sourceType && sourceId ? [{ sourceType, sourceId }] : [];
  });

  if (normalized.length === 0) {
    return <p className="mt-4 text-xs text-muted-foreground">No source citations returned.</p>;
  }

  return (
    <div className="mt-4">
      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Citations</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {normalized.map(({ sourceType, sourceId }) => (
          <Link
            key={`${sourceType}-${sourceId}`}
            to={citationHref(sourceType, sourceId)}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-cyan-300/30 bg-cyan-300/5 px-2.5 text-xs text-cyan-200 hover:bg-cyan-300/10"
          >
            {humanizeStatus(sourceType)} {sourceId}
            <ExternalLink className="size-3" aria-hidden="true" />
          </Link>
        ))}
      </div>
    </div>
  );
}

export function ToolTrace({ trace }: { trace: Record<string, unknown>[] }) {
  if (trace.length === 0) return null;

  return (
    <details className="mt-4 rounded-md border border-border/80 bg-background/30 px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-muted-foreground">
        <Wrench className="size-3.5" aria-hidden="true" /> Tool trace ({trace.length})
      </summary>
      <div className="mt-3 space-y-2">
        {trace.map((item, index) => (
          <pre key={index} className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[0.68rem] leading-5 text-muted-foreground">
            {JSON.stringify(item, null, 2)}
          </pre>
        ))}
      </div>
    </details>
  );
}
