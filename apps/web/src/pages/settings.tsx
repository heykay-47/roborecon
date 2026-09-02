import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">This workspace is intentionally read-only. Deployment and provider configuration stay outside the browser.</p>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">Workspace policy</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Matching authority</dt><dd className="mt-1 text-sm">Deterministic reconciliation policy</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">AI authority</dt><dd className="mt-1 text-sm">Advisory only; cannot mutate outcomes</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Review outcomes</dt><dd className="mt-1 text-sm">Approve or reject are terminal</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Money model</dt><dd className="mt-1 text-sm">Integer INR minor units</dd></div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

export default SettingsPage;
