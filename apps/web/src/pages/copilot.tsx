import { useState } from "react";
import { IconAlertCircle, IconMessageCircle, IconSend } from "@tabler/icons-react";
import { Alert } from "@/components/alert";
import { CitationList, ToolTrace } from "@/components/evidence";
import { PageHeader } from "@/components/page-header";
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

const SEEDED_QUESTION = "Why is this settlement lower than captured payments?";

function Calculation({ calculation }: { calculation: Record<string, unknown> | null }) {
  if (!calculation) return <p className="text-sm text-muted-foreground">No calculation was available.</p>;
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
       <CardHeader className="panel-header items-start"><div><CardTitle className="text-sm font-medium">Answer from saved data</CardTitle><p className="mt-1 text-xs text-muted-foreground">Uses saved settlement records</p></div><Badge variant="outline" className={fallback ? "text-warning" : "text-primary"}>{fallback ? "Rules-based answer" : "AI suggestion"}</Badge></CardHeader>
       <CardContent className="space-y-5">
        <p className="break-words whitespace-pre-wrap text-sm leading-7 text-foreground">{answer.answer}</p>
        <div className="border-t border-border pt-4"><h3 className="mb-3 text-sm font-medium">How the amount was calculated</h3><Calculation calculation={answer.calculation} /></div>
        <CitationList citations={answer.citations} />
        <ToolTrace trace={answer.toolTrace} />
        {answer.errorCode && <p className="text-xs text-warning">Why the rules-based answer was used: {answer.errorCode}</p>}
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

  if (runs.isLoading || settlements.isLoading) return <PageState kind="loading" headingLevel="h1" title="Loading settlement data…" description="Getting the run and settlement records." />;
  if (runs.isError) return <PageState kind="error" headingLevel="h1" title="Could not load runs" description={runs.error.message} />;
  if (settlements.isError) return <PageState kind="error" headingLevel="h1" title="Could not load settlement data" description={settlements.error.message} />;

  const submit = () => {
    if (!selectedSettlementId || !question.trim()) return;
    copilot.mutate({ question: question.trim(), runId: selectedRunId, settlementId: selectedSettlementId });
  };
  const copilotError = copilot.error;
  const errorMessage = copilotError instanceof ApiError ? copilotError.message : copilotError?.message;

  return (
    <div className="page-stack">
      <PageHeader
        title="Copilot"
        status={<Badge variant="outline" className="text-warning"><IconMessageCircle aria-hidden="true" /> Read-only</Badge>}
        description="Ask about a settlement. Answers use saved records; matching rules and source data are the authority."
      />

      <Card className="gap-0 py-0">
        <CardHeader className="panel-header"><CardTitle className="text-sm font-medium">Ask about a settlement</CardTitle></CardHeader>
        <CardContent className="space-y-5 py-4">
          <div className="grid gap-3 md:grid-cols-2">
             <label className="field-label" htmlFor="copilot-run">Run<Select id="copilot-run" value={selectedRunId ?? ""} onChange={(event) => { setRunId(event.target.value); setSettlementId(""); copilot.reset(); }}><option value="">{hasRunCatalog ? "Choose a run" : "No completed runs"}</option>{runs.data?.items.map((run) => <option key={run.runId} value={run.runId}>{run.runId} · {run.status}</option>)}</Select></label>
             <label className="field-label" htmlFor="copilot-settlement">Settlement<Select id="copilot-settlement" value={selectedSettlementId ?? ""} onChange={(event) => { setSettlementId(event.target.value); copilot.reset(); }} disabled={!settlements.data || settlements.data.items.length === 0}><option value="">Choose a settlement</option>{settlements.data?.items.map((settlement) => <option key={settlement.sourceId} value={settlement.sourceId ?? ""}>{settlement.reference ?? settlement.sourceId}</option>)}</Select></label>
          </div>
          <label className="block text-sm font-medium" htmlFor="copilot-question">Question<Textarea id="copilot-question" value={question} onChange={(event) => { setQuestion(event.target.value); copilot.reset(); }} className="mt-2 min-h-28" maxLength={2000} /></label>
           <div className="flex flex-wrap items-center gap-3"><Button type="button" onClick={submit} disabled={!hasContext || !question.trim() || copilot.isPending}><IconSend aria-hidden="true" /> {copilot.isPending ? "Checking records…" : "Explain settlement"}</Button>{!hasContext && <span className="text-sm text-muted-foreground">Choose a settlement to continue.</span>}</div>
        </CardContent>
      </Card>

      {copilot.isError && <Alert tone="danger"><span className="flex items-start gap-2 text-danger"><IconAlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" /><span>Could not explain this settlement. {errorMessage ?? "Something went wrong."}</span></span></Alert>}
      {copilot.data && <Answer answer={copilot.data} />}
      {!copilot.data && !copilot.isError && settlements.data?.items.length === 0 && <PageState kind="empty" title="No settlement data" description="Reset the demo data or sync a batch before asking about a settlement." />}
    </div>
  );
}

export default CopilotPage;
