import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type AlertTone = "info" | "success" | "warning" | "danger";

const toneClasses: Record<AlertTone, string> = {
  info: "border-primary/30 bg-primary/8 text-foreground",
  success: "border-success/30 bg-success/8 text-foreground",
  warning: "border-warning/35 bg-warning/10 text-foreground",
  danger: "border-danger/35 bg-danger/10 text-foreground",
};

export function Alert({
  tone = "info",
  children,
  role = tone === "danger" ? "alert" : "status",
  className,
}: {
  tone?: AlertTone;
  children: ReactNode;
  role?: "alert" | "status";
  className?: string;
}) {
  return (
    <div role={role} className={cn("rounded-md border px-3.5 py-3 text-sm leading-6", toneClasses[tone], className)}>
      {children}
    </div>
  );
}
