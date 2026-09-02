interface MetricCardProps {
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "positive" | "warning";
}

export function MetricCard({ label, value, detail, tone = "default" }: MetricCardProps) {
  const valueClass =
    tone === "positive"
       ? "text-success"
      : tone === "warning"
         ? "text-warning"
        : "text-foreground";

  return (
    <article className="border-b border-border px-4 py-4 first:pl-0 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${valueClass}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </article>
  );
}
