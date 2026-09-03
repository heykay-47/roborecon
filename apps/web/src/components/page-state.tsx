import type { ReactNode } from "react";
import { IconAlertCircle, IconDatabase, IconLoader2 } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";

interface PageStateProps {
  kind: "loading" | "error" | "empty";
  title: string;
  description: string;
  action?: ReactNode;
  headingLevel?: "h1" | "h2";
}

export function PageState({ kind, title, description, action, headingLevel = "h2" }: PageStateProps) {
  const Icon = kind === "loading" ? IconLoader2 : kind === "error" ? IconAlertCircle : IconDatabase;
  const Heading = headingLevel;

  return (
    <div
      className="flex min-h-56 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border bg-card px-6 py-10 text-center shadow-xs"
      role={kind === "loading" ? "status" : "alert"}
      aria-live="polite"
    >
      <Icon
        className={kind === "loading" ? "size-5 animate-spin text-primary" : "size-5 text-muted-foreground"}
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
