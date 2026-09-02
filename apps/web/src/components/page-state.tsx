import type { ReactNode } from "react";
import { AlertCircle, Database, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PageStateProps {
  kind: "loading" | "error" | "empty";
  title: string;
  description: string;
  action?: ReactNode;
  headingLevel?: "h1" | "h2";
}

export function PageState({ kind, title, description, action, headingLevel = "h2" }: PageStateProps) {
  const Icon = kind === "loading" ? LoaderCircle : kind === "error" ? AlertCircle : Database;
  const Heading = headingLevel;

  return (
    <div
      className="flex min-h-56 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center"
      role={kind === "loading" ? "status" : "alert"}
      aria-live="polite"
    >
      <Icon
        className={kind === "loading" ? "size-5 animate-spin text-cyan-300" : "size-5 text-muted-foreground"}
        aria-hidden="true"
      />
      <div>
        <Heading className="text-sm font-semibold text-foreground">{title}</Heading>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onClick}>
      Try again
    </Button>
  );
}
