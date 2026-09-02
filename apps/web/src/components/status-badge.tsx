import { Badge } from "@/components/ui/badge";
import { humanizeStatus, statusClass } from "@/lib/status-colors";

export function StatusBadge({ value }: { value: string }) {
  return (
    <Badge variant="outline" className={statusClass(value)}>
      {humanizeStatus(value)}
    </Badge>
  );
}
