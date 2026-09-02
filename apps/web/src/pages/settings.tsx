import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SettingsPage() {
  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">This workspace is read-only. Deployment and provider settings are managed outside the browser.</p>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">How matching works</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Matching rules</dt><dd className="mt-1 text-sm">Fixed rules decide each match</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">AI role</dt><dd className="mt-1 text-sm">Suggestions only; AI cannot change results</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Review decisions</dt><dd className="mt-1 text-sm">Approve or reject ends the review</dd></div>
            <div><dt className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Amounts</dt><dd className="mt-1 text-sm">INR is stored in paise</dd></div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

export default SettingsPage;
