import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-bull/15 text-bull ring-bull/30",
  partial: "bg-caution/15 text-caution ring-caution/30",
  running: "bg-info/15 text-info ring-info/30",
  pending: "bg-muted text-muted-foreground ring-border",
  failed: "bg-bear/15 text-bear ring-bear/30",
  timed_out: "bg-caution/15 text-caution ring-caution/30",
};

const STATUS_LABELS: Record<string, string> = {
  completed: "Completed",
  partial: "Partial",
  running: "Running",
  pending: "Pending",
  failed: "Failed",
  timed_out: "Timed Out",
};

export function ScanStatusBadge({ status }: { status: string }) {
  const styles =
    STATUS_STYLES[status] ?? "bg-muted text-muted-foreground ring-border";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        styles
      )}
    >
      {label}
    </span>
  );
}
