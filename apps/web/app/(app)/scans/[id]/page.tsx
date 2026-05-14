import { notFound } from "next/navigation";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { fetchScanRun, fetchScanRunCandidates } from "@/lib/queries/scans";
import {
  fetchRunCategoryBreakdown,
  fetchRunEntryRejections,
  fetchRunExclusions,
} from "@/lib/queries/diagnostics";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { CategoryBadge } from "@/components/candidates/state-badge";

export const dynamic = "force-dynamic";

function StatCard({
  label,
  value,
  dim,
}: {
  label: string;
  value: string | number | null;
  dim?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold tabular-nums ${dim ? "text-muted-foreground" : "text-foreground"}`}
      >
        {value ?? "—"}
      </p>
    </div>
  );
}

function formatDuration(
  started: string,
  completed: string | null
): string {
  if (!completed) return "—";
  const s = Math.round(
    (new Date(completed).getTime() - new Date(started).getTime()) / 1000
  );
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default async function ScanRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [run, candidates, exclusions, rejections, breakdown] =
    await Promise.all([
      fetchScanRun(id),
      fetchScanRunCandidates(id),
      fetchRunExclusions(id),
      fetchRunEntryRejections(id),
      fetchRunCategoryBreakdown(id),
    ]);

  if (!run) notFound();

  return (
    <div className="space-y-6 p-6">
      {/* Back link */}
      <Link
        href="/scans"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Scan History
      </Link>

      {/* Header */}
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            Scan Run Detail
          </h1>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
            {run.id}
          </p>
        </div>
        <ScanStatusBadge status={run.status} />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <StatCard
          label="Started"
          value={new Date(run.started_at).toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        />
        <StatCard
          label="Duration"
          value={formatDuration(run.started_at, run.completed_at)}
          dim
        />
        <StatCard label="Trigger" value={run.triggered_by} dim />
        <StatCard label="Scanned" value={run.assets_scanned} />
        <StatCard label="Passed Filter" value={run.assets_passed_filter} />
        <StatCard label="Clean" value={run.candidates_clean} />
        <StatCard label="Ugly" value={run.candidates_ugly} />
      </div>

      {run.error_message && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <span className="font-medium">Error: </span>
          {run.error_message}
        </div>
      )}

      {/* Candidates */}
      <div>
        <h2 className="mb-3 text-sm font-medium text-foreground">
          Candidates ({candidates.length})
        </h2>
        {candidates.length === 0 ? (
          <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            No candidates for this run.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Symbol</th>
                  <th className="px-4 py-3 font-medium">Cat</th>
                  <th className="px-4 py-3 font-medium text-right">Rank</th>
                  <th className="px-4 py-3 font-medium text-right">Score</th>
                  <th className="px-4 py-3 font-medium text-right">Prob%</th>
                  <th className="px-4 py-3 font-medium text-right">Entry</th>
                  <th className="px-4 py-3 font-medium text-right">Target</th>
                  <th className="px-4 py-3 font-medium text-right">Stop</th>
                  <th className="px-4 py-3 font-medium text-right">RR</th>
                  <th className="px-4 py-3 font-medium">Size</th>
                  <th className="px-4 py-3 font-medium">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {candidates.map((c) => (
                  <tr key={c.id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-2.5 font-mono font-medium text-foreground">
                      <Link
                        href={`/assets/${encodeURIComponent(c.symbol)}`}
                        className="hover:underline"
                      >
                        {c.symbol}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <CategoryBadge
                        category={c.category as "clean" | "ugly"}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                      #{c.rank}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums font-medium">
                      {c.score_total ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                      {c.probability_pct != null
                        ? `${c.probability_pct}%`
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      ${c.entry_price.toFixed(4)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-emerald-400">
                      ${c.exit_price.toFixed(4)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-red-400">
                      ${c.stop_loss.toFixed(4)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                      {c.reward_risk_ratio?.toFixed(1) ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">
                      {c.suggested_size_bucket}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground capitalize">
                      {c.state.replace(/_/g, " ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Diagnostics — exclusion / rejection / category breakdown panels */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Hard-filter exclusions */}
        <section>
          <h2 className="mb-3 text-sm font-medium text-foreground">
            Hard-Filter Exclusions ({exclusions.reduce((s, e) => s + e.count, 0)})
          </h2>
          {exclusions.length === 0 ? (
            <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              No exclusions for this run.
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Reason</th>
                    <th className="px-4 py-2.5 font-medium text-right">Count</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {exclusions.map((e) => (
                    <tr key={e.reason}>
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                        {e.reason}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {e.count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Entry-engine rejections */}
        <section>
          <h2 className="mb-3 text-sm font-medium text-foreground">
            Entry-Engine Rejections ({rejections.length})
          </h2>
          {rejections.length === 0 ? (
            <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              No entry rejections for this run.
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Symbol</th>
                    <th className="px-4 py-2.5 font-medium">Setup</th>
                    <th className="px-4 py-2.5 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rejections.map((r, i) => (
                    <tr key={`${r.symbol}-${i}`}>
                      <td className="px-4 py-2 font-mono font-medium text-foreground">
                        <Link
                          href={`/assets/${encodeURIComponent(r.symbol)}`}
                          className="hover:underline"
                        >
                          {r.symbol}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground capitalize">
                        {r.setup_type.replace(/_/g, " ")}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                        {r.rejection_reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Watchlist / Low Score counts */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-foreground">
          Below Selection Threshold
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
          <StatCard label="Watchlist" value={breakdown.watchlist} dim />
          <StatCard label="Low Score" value={breakdown.low_score} dim />
        </div>
      </section>
    </div>
  );
}
