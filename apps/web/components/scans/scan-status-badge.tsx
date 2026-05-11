import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  partial: "bg-yellow-500/15 text-yellow-400 ring-yellow-500/30",
  running: "bg-blue-500/15 text-blue-400 ring-blue-500/30",
  pending: "bg-muted text-muted-foreground ring-border",
  failed: "bg-red-500/15 text-red-400 ring-red-500/30",
};

const STATUS_LABELS: Record<string, string> = {
  completed: "Completed",
  partial: "Partial",
  running: "Running",
  pending: "Pending",
  failed: "Failed",
};

export function ScanStatusBadge({ status }: { status: string }) {
  const styles =
    STATUS_STYLES[status] ?? "bg-muted text-muted-foreground ring-border";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        styles
      )}
    >
      {label}
    </span>
  );
}
