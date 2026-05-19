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
import { PageShell } from "@/components/shell/page-shell";

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
    <div className="rounded-xl border border-border/70 bg-card p-4 shadow-card">
      <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`mt-2 text-xl font-semibold tabular-nums tracking-tight ${dim ? "text-muted-foreground" : "text-foreground"}`}
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
    <PageShell>
      <Link
        href="/scans"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Scan History
      </Link>

      <header className="flex items-center gap-3">
        <div>
          <h1 className="text-[1.375rem] font-semibold tracking-tight text-foreground">
            Scan Run Detail
          </h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {run.id}
          </p>
        </div>
        <ScanStatusBadge status={run.status} />
      </header>

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
        <div className="rounded-xl border border-bear/30 bg-bear/10 px-4 py-3 text-sm text-bear">
          <span className="font-medium">Error: </span>
          {run.error_message}
        </div>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">
          Candidates ({candidates.length})
        </h2>
        {candidates.length === 0 ? (
          <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
            No candidates for this run.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border/70 bg-card shadow-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
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
              <tbody className="divide-y divide-border/50">
                {candidates.map((c) => (
                  <tr key={c.id} className="transition-colors hover:bg-muted/20">
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
                    <td className="px-4 py-2.5 text-right tabular-nums text-bull">
                      ${c.exit_price.toFixed(4)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-bear">
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
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">
            Hard-Filter Exclusions ({exclusions.reduce((s, e) => s + e.count, 0)})
          </h2>
          {exclusions.length === 0 ? (
            <div className="flex h-24 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
              No exclusions for this run.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border/70 bg-card shadow-card">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Reason</th>
                    <th className="px-4 py-2.5 font-medium text-right">Count</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
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

        <section>
          <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">
            Entry-Engine Rejections ({rejections.length})
          </h2>
          {rejections.length === 0 ? (
            <div className="flex h-24 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
              No entry rejections for this run.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border/70 bg-card shadow-card">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Symbol</th>
                    <th className="px-4 py-2.5 font-medium">Setup</th>
                    <th className="px-4 py-2.5 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
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

      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">
          Below Selection Threshold
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
          <StatCard label="Watchlist" value={breakdown.watchlist} dim />
          <StatCard label="Low Score" value={breakdown.low_score} dim />
        </div>
      </section>
    </PageShell>
  );
}
