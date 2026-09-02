import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export function NotFoundPage({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-6">
      <div className="border-b border-border pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-12 text-center">
        <p className="text-sm text-muted-foreground">This route does not exist in the Roborecon workspace.</p>
        <Link to="/" className="mt-4 inline-flex items-center gap-2 text-sm text-cyan-200 hover:text-cyan-100">
          <ArrowLeft className="size-4" aria-hidden="true" /> Return to overview
        </Link>
      </div>
    </div>
  );
}

export default NotFoundPage;
