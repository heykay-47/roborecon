import { useState } from "react";
import { CircleAlert, MessageSquare, Send } from "lucide-react";
import { CitationList, ToolTrace } from "@/components/evidence";
import { PageState } from "@/components/page-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCopilot, useRuns, useTransactions } from "@/hooks/use-roborecon";
import { ApiError } from "@/lib/api";
import { valueToText } from "@/lib/evidence";
import type { CopilotAnswer } from "@/types/api";

const SEEDED_QUESTION = "Explain the settlement reconciliation arithmetic for this settlement.";

function Calculation({ calculation }: { calculation: Record<string, unknown> | null }) {
  if (!calculation) return <p className="text-sm text-muted-foreground">No calculation was returned.</p>;
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {Object.entries(calculation).map(([key, value]) => (
        <div key={key}><dt className="text-xs text-muted-foreground">{key}</dt><dd className="mt-1 break-words font-mono text-sm tabular-nums">{valueToText(value)}</dd></div>
      ))}
    </dl>
  );
}

function Answer({ answer }: { answer: CopilotAnswer }) {
  const fallback = answer.mode === "deterministicFallback";
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3"><div><CardTitle className="text-sm font-medium">Grounded answer</CardTitle><p className="mt-1 text-xs text-muted-foreground">Read-only settlement context</p></div><Badge variant="outline" className={fallback ? "text-amber-200" : "text-cyan-200"}>{fallback ? "Deterministic fallback" : "Provider advisory"}</Badge></CardHeader>
      <CardContent className="space-y-5">
        <p className="break-words whitespace-pre-wrap text-sm leading-7 text-foreground">{answer.answer}</p>
        <div className="border-t border-border pt-4"><h3 className="mb-3 text-sm font-medium">Calculation</h3><Calculation calculation={answer.calculation} /></div>
        <CitationList citations={answer.citations} />
        <ToolTrace trace={answer.toolTrace} />
        {answer.errorCode && <p className="text-xs text-amber-200">Fallback reason: {answer.errorCode}</p>}
      </CardContent>
    </Card>
  );
}

export function CopilotPage() {
  const runs = useRuns(1, 50);
  const [question, setQuestion] = useState(SEEDED_QUESTION);
  const [runId, setRunId] = useState("");
  const [settlementId, setSettlementId] = useState("");
  const copilot = useCopilot();
  const selectedRun = runs.data?.items.find((run) => run.runId === (runId || runs.data?.items[0]?.runId));
  const selectedRunId = selectedRun?.runId;
  const hasRunCatalog = Boolean(runs.data?.items.length);
  const settlements = useTransactions({
    page: 1,
    pageSize: 200,
    sourceType: "settlement",
    batchId: selectedRun?.batchId,
    enabled: Boolean(selectedRun?.batchId) || runs.data?.items.length === 0,
  });
  const selectedSettlementId = settlementId || settlements.data?.items[0]?.sourceId || undefined;
  const hasContext = Boolean(selectedSettlementId && (selectedRunId || !hasRunCatalog));

  if (runs.isLoading || settlements.isLoading) return <PageState kind="loading" headingLevel="h1" title="Loading Copilot context" description="Reading the selected run's settlement records before enabling grounded answers." />;
  if (runs.isError) return <PageState kind="error" headingLevel="h1" title="Unable to load Copilot runs" description={runs.error.message} />;
  if (settlements.isError) return <PageState kind="error" headingLevel="h1" title="Unable to load settlement context" description={settlements.error.message} />;

  const submit = () => {
    if (!selectedSettlementId || !question.trim()) return;
    copilot.mutate({ question: question.trim(), runId: selectedRunId, settlementId: selectedSettlementId });
  };
  const copilotError = copilot.error;
  const errorMessage = copilotError instanceof ApiError ? copilotError.message : copilotError?.message;

  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-6"><div className="flex items-center gap-3"><MessageSquare className="size-5 text-cyan-200" aria-hidden="true" /><h1 className="text-3xl font-semibold tracking-tight">Copilot</h1><Badge variant="outline" className="text-amber-200">Read-only</Badge></div><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Ask for a grounded settlement explanation. Deterministic policy and persisted source evidence remain authoritative.</p></div>

      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">Settlement question</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="copilot-run">Run context<Select id="copilot-run" value={selectedRunId ?? ""} onChange={(event) => { setRunId(event.target.value); setSettlementId(""); copilot.reset(); }}><option value="">{hasRunCatalog ? "Select run" : "No completed run available"}</option>{runs.data?.items.map((run) => <option key={run.runId} value={run.runId}>{run.runId} · {run.status}</option>)}</Select></label>
            <label className="space-y-1.5 text-xs font-medium text-muted-foreground" htmlFor="copilot-settlement">Settlement context<Select id="copilot-settlement" value={selectedSettlementId ?? ""} onChange={(event) => { setSettlementId(event.target.value); copilot.reset(); }} disabled={!settlements.data || settlements.data.items.length === 0}><option value="">Select settlement</option>{settlements.data?.items.map((settlement) => <option key={settlement.sourceId} value={settlement.sourceId ?? ""}>{settlement.reference ?? settlement.sourceId}</option>)}</Select></label>
          </div>
          <label className="block text-sm font-medium" htmlFor="copilot-question">Question<Textarea id="copilot-question" value={question} onChange={(event) => { setQuestion(event.target.value); copilot.reset(); }} className="mt-2 min-h-28" maxLength={2000} /></label>
          <div className="flex flex-wrap items-center gap-3"><Button type="button" onClick={submit} disabled={!hasContext || !question.trim() || copilot.isPending}><Send aria-hidden="true" /> {copilot.isPending ? "Explaining..." : "Explain settlement"}</Button>{!hasContext && <span className="text-sm text-muted-foreground">A settlement record is required.</span>}</div>
        </CardContent>
      </Card>

      {copilot.isError && <div className="flex items-start gap-2 rounded-lg border border-rose-300/30 bg-rose-300/5 p-4 text-sm text-rose-200" role="alert"><CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /><span>Unable to explain this settlement. {errorMessage ?? "The API returned an unknown error."}</span></div>}
      {copilot.data && <Answer answer={copilot.data} />}
      {!copilot.data && !copilot.isError && settlements.data?.items.length === 0 && <PageState kind="empty" title="No settlement context" description="Reset or sync a batch before asking Copilot for a grounded settlement explanation." />}
    </div>
  );
}

export default CopilotPage;
