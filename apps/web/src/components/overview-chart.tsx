import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatPercent } from "@/lib/format";
import { humanizeStatus } from "@/lib/status-colors";
import type { ScenarioMetric } from "@/types/api";

export default function OverviewChart({ scenarios }: { scenarios: ScenarioMetric[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={scenarios} margin={{ top: 8, right: 8, left: -18, bottom: 8 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="scenarioClass"
          tickFormatter={humanizeStatus}
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={(value: number) => `${value}%`}
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            color: "var(--popover-foreground)",
          }}
          formatter={(value) => [formatPercent(typeof value === "number" ? value : null), "Rate"]}
          labelFormatter={(label) => humanizeStatus(String(label))}
        />
        <Bar dataKey="matchRate" name="Match rate" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
        <Bar dataKey="precision" name="Precision" fill="var(--chart-2)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
