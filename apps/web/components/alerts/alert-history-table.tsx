"use client";

import Link from "next/link";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { AlertHistoryRow } from "@/lib/queries/alerts";

const DELIVERY_STYLES: Record<string, string> = {
  sent: "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30",
  failed: "bg-red-500/15 text-red-400 ring-red-500/30",
  skipped: "bg-muted text-muted-foreground ring-border",
};

const TYPE_STYLES: Record<string, string> = {
  new_candidate: "bg-blue-500/15 text-blue-400 ring-blue-500/30",
  state_change: "bg-yellow-500/15 text-yellow-400 ring-yellow-500/30",
  invalidation: "bg-orange-500/15 text-orange-400 ring-orange-500/30",
  system: "bg-purple-500/15 text-purple-400 ring-purple-500/30",
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
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
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
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        No alerts sent yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
            <th className="px-4 py-3 font-medium">Sent</th>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium">Type</th>
            <th className="px-4 py-3 font-medium">Channel</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Scan Run</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr
              key={row.id}
              className="transition-colors hover:bg-muted/30"
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
                {row.symbol}
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
                    className="mt-0.5 max-w-[200px] truncate text-xs text-red-400"
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
