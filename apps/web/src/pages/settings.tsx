import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";

export function SettingsPage() {
  return (
    <div className="page-stack">
      <PageHeader title="Settings" description="This workspace is read-only. Deployment and provider settings are managed outside the browser." />
      <Card className="gap-0 py-0">
        <CardHeader className="panel-header"><CardTitle className="text-sm font-medium">How matching works</CardTitle></CardHeader>
        <CardContent>
          <dl className="divide-y divide-border">
            <div className="grid gap-1 py-3 first:pt-0 sm:grid-cols-[12rem_1fr] sm:gap-6"><dt className="eyebrow">Matching rules</dt><dd className="text-sm">Fixed rules decide each match</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[12rem_1fr] sm:gap-6"><dt className="eyebrow">AI role</dt><dd className="text-sm">Suggestions only; AI cannot change results</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[12rem_1fr] sm:gap-6"><dt className="eyebrow">Review decisions</dt><dd className="text-sm">Approve or reject ends the review</dd></div>
            <div className="grid gap-1 py-3 last:pb-0 sm:grid-cols-[12rem_1fr] sm:gap-6"><dt className="eyebrow">Amounts</dt><dd className="text-sm">INR is stored in paise</dd></div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

export default SettingsPage;
