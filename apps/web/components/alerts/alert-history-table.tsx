"use client";

import Link from "next/link";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { AlertHistoryRow } from "@/lib/queries/alerts";

const DELIVERY_STYLES: Record<string, string> = {
  sent: "bg-bull/15 text-bull ring-bull/30",
  failed: "bg-bear/15 text-bear ring-bear/30",
  skipped: "bg-muted text-muted-foreground ring-border",
};

const TYPE_STYLES: Record<string, string> = {
  new_candidate: "bg-info/15 text-info ring-info/30",
  state_change: "bg-caution/15 text-caution ring-caution/30",
  invalidation: "bg-bear/15 text-bear ring-bear/30",
  system: "bg-muted text-muted-foreground ring-border",
};

function Badge({
  label,
  styles,
}: {
  label: string;
  styles: string;
}) {
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

interface Props {
  rows: AlertHistoryRow[];
}

export function AlertHistoryTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
        No alerts sent yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border/70 bg-card shadow-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <th className="px-4 py-3 font-medium">Sent</th>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium">Type</th>
            <th className="px-4 py-3 font-medium">Channel</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Scan Run</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {rows.map((row) => (
            <tr
              key={row.id}
              className="transition-colors hover:bg-muted/20"
            >
              <td className="px-4 py-3 font-mono tabular-nums text-muted-foreground">
                {row.sent_at
                  ? formatRelativeTime(row.sent_at)
                  : formatRelativeTime(row.created_at)}
                <div className="mt-0.5 text-xs text-muted-foreground/60">
                  {new Date(
                    row.sent_at ?? row.created_at
                  ).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </td>
              <td className="px-4 py-3 font-mono font-medium text-foreground">
                <Link
                  href={`/assets/${encodeURIComponent(row.symbol)}`}
                  className="hover:underline"
                >
                  {row.symbol}
                </Link>
              </td>
              <td className="px-4 py-3">
                <Badge
                  label={row.alert_type.replace(/_/g, " ")}
                  styles={
                    TYPE_STYLES[row.alert_type] ??
                    "bg-muted text-muted-foreground ring-border"
                  }
                />
              </td>
              <td className="px-4 py-3 capitalize text-muted-foreground">
                {row.channel}
              </td>
              <td className="px-4 py-3">
                <Badge
                  label={row.delivery_status}
                  styles={
                    DELIVERY_STYLES[row.delivery_status] ??
                    "bg-muted text-muted-foreground ring-border"
                  }
                />
                {row.error_message && (
                  <div
                    className="mt-0.5 max-w-[200px] truncate text-xs text-bear"
                    title={row.error_message}
                  >
                    {row.error_message}
                  </div>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                <Link
                  href={`/scans/${row.scan_run_id}`}
                  className="underline-offset-2 hover:text-foreground hover:underline"
                >
                  {row.scan_run_id.slice(0, 8)}…
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
