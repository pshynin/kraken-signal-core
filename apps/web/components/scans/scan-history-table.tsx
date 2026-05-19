"use client";

import Link from "next/link";
import { ScanStatusBadge } from "./scan-status-badge";
import { formatRelativeTime } from "@/lib/utils";
import type { ScanRunListRow } from "@/lib/queries/scans";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function Num({ n }: { n: number | null }) {
  if (n === null) return <span className="text-muted-foreground">—</span>;
  return <>{n.toLocaleString()}</>;
}

interface Props {
  rows: ScanRunListRow[];
}

export function ScanHistoryTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
        No scan runs recorded yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border/70 bg-card shadow-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Trigger</th>
            <th className="px-4 py-3 font-medium text-right">Duration</th>
            <th className="px-4 py-3 font-medium text-right">Scanned</th>
            <th className="px-4 py-3 font-medium text-right">Passed</th>
            <th className="px-4 py-3 font-medium text-right">Clean</th>
            <th className="px-4 py-3 font-medium text-right">Ugly</th>
            <th className="px-4 py-3 font-medium text-right">Alerts</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {rows.map((row) => (
            <tr
              key={row.id}
              className="group transition-colors hover:bg-muted/20"
            >
              <td className="px-4 py-3 font-mono tabular-nums">
                <Link
                  href={`/scans/${row.id}`}
                  className="text-foreground underline-offset-2 group-hover:underline"
                >
                  {formatRelativeTime(row.started_at)}
                </Link>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {new Date(row.started_at).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </td>
              <td className="px-4 py-3">
                <ScanStatusBadge status={row.status} />
                {row.error_message && (
                  <div
                    className="mt-0.5 max-w-[180px] truncate text-xs text-bear"
                    title={row.error_message}
                  >
                    {row.error_message}
                  </div>
                )}
              </td>
              <td className="px-4 py-3 text-muted-foreground capitalize">
                {row.triggered_by}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                {formatDuration(row.duration_seconds)}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-foreground">
                <Num n={row.assets_scanned} />
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-foreground">
                <Num n={row.assets_passed_filter} />
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-bull">
                <Num n={row.candidates_clean} />
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-caution">
                <Num n={row.candidates_ugly} />
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-foreground">
                <Num n={row.alerts_sent} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
