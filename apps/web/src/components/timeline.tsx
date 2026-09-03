import type { ReactNode } from "react";

export function Timeline({ children }: { children: ReactNode }) {
  return (
    <ol className="relative space-y-5 before:absolute before:bottom-5 before:left-[0.3rem] before:top-1 before:w-px before:bg-border">
      {children}
    </ol>
  );
}

export function TimelineItem({ children }: { children: ReactNode }) {
  return (
    <li className="relative pl-8">
      <span className="absolute left-1 top-1.5 size-2.5 rounded-full border-2 border-card bg-primary ring-4 ring-primary/10" aria-hidden="true" />
      {children}
    </li>
  );
}
