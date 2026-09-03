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
    <article className="flex min-h-28 flex-col justify-between border-b border-border px-4 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <p className="eyebrow">
        {label}
      </p>
      <p className={`mt-3 font-mono text-2xl font-semibold tabular-nums ${valueClass}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </article>
  );
}
