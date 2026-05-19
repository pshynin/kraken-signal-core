import {
  TrendingUp,
  AlertTriangle,
  Bell,
  Database,
  Clock,
  Loader2,
} from "lucide-react";
import { createServerClient } from "@/lib/supabase/server";
import { formatRelativeTime } from "@/lib/utils";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import type { ScanRunRow } from "@kraken-signal/shared-types";

export const dynamic = "force-dynamic";

// Statuses that represent a run that has finished producing (or failing to
// produce) a result snapshot. 'timed_out' rows are stuck-running rows the
// scanner auto-finalises at next startup — they have completed_at = NULL, so
// the finalized query orders by started_at (always populated, monotonic).
const FINALIZED_STATUSES = [
  "completed",
  "partial",
  "failed",
  "timed_out",
] as const;

// ── Data fetching ─────────────────────────────────────────────────────────────

async function getOverviewData(): Promise<{
  finalizedRun: ScanRunRow | null;
  runningRun: ScanRunRow | null;
  activeAssets: number;
}> {
  try {
    const client = createServerClient();
    const [finalizedRes, runningRes, assetRes] = await Promise.all([
      client
        .from("scan_runs")
        .select("*")
        .in("status", FINALIZED_STATUSES as unknown as string[])
        .order("started_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
      client
        .from("scan_runs")
        .select("*")
        .eq("status", "running")
        .order("started_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
      client
        .from("assets")
        .select("*", { count: "exact", head: true })
        .eq("is_active", true),
    ]);
    return {
      finalizedRun: (finalizedRes.data as ScanRunRow | null) ?? null,
      runningRun: (runningRes.data as ScanRunRow | null) ?? null,
      activeAssets: assetRes.count ?? 0,
    };
  } catch {
    return { finalizedRun: null, runningRun: null, activeAssets: 0 };
  }
}

/** Whole-second duration between started/completed, or null if unknown. */
function runDurationSeconds(run: ScanRunRow): number | null {
  if (!run.completed_at || !run.started_at) return null;
  return Math.round(
    (new Date(run.completed_at).getTime() -
      new Date(run.started_at).getTime()) /
      1000
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

// ── Stat card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  Icon: React.ElementType;
  accent?: "green" | "amber" | "default";
}

function StatCard({ label, value, sub, Icon, accent = "default" }: StatCardProps) {
  const iconColor =
    accent === "green"
      ? "text-bull"
      : accent === "amber"
        ? "text-caution"
        : "text-muted-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <Icon className={`h-4 w-4 ${iconColor}`} />
      </div>
      <div>
        <p className="text-2xl font-semibold tabular-nums text-foreground">{value}</p>
        {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
      </div>
    </div>
  );
}

// ── Current run strip ─────────────────────────────────────────────────────────
// Compact one-line live status. No result counters: the running row's result
// columns are NULL until finalisation, so showing them would be misleading.

function CurrentRunStrip({ run }: { run: ScanRunRow }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2.5 text-sm">
      <span className="inline-flex items-center gap-1.5 font-medium text-primary">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Running
      </span>
      <span className="text-muted-foreground">
        started {formatRelativeTime(run.started_at)}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="text-muted-foreground capitalize">
        triggered by {run.triggered_by}
      </span>
    </div>
  );
}

// ── Most recent finalized run card ────────────────────────────────────────────

function FinalizedRunCard({ run }: { run: ScanRunRow }) {
  const duration = runDurationSeconds(run);
  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-sm font-medium text-foreground">
          Most Recent Finalized Run
        </h2>
        <ScanStatusBadge status={run.status} />
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Started</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {formatRelativeTime(run.started_at)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Completed</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {run.completed_at ? formatRelativeTime(run.completed_at) : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Duration</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {duration != null ? formatDuration(duration) : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Triggered by</p>
          <p className="mt-0.5 font-medium text-foreground capitalize">
            {run.triggered_by}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Assets scanned</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {run.assets_scanned ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Passed filter</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {run.assets_passed_filter ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Clean candidates</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {run.candidates_clean ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Ugly candidates</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {run.candidates_ugly ?? "—"}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border pt-3 text-xs">
        <span className="text-muted-foreground">
          Alerts sent:{" "}
          <span className="font-medium text-foreground tabular-nums">
            {run.alerts_sent ?? "—"}
          </span>
        </span>
        <span className="font-mono text-muted-foreground/60">
          {run.id.slice(0, 8)}
        </span>
      </div>

      {run.error_message && (
        <p className="rounded-md bg-bear/10 px-3 py-2 text-xs text-bear font-mono">
          {run.error_message}
        </p>
      )}
    </div>
  );
}

// ── Empty / first-run states ──────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="rounded-lg border border-border bg-card p-12 text-center space-y-3">
      <Clock className="mx-auto h-8 w-8 text-muted-foreground" />
      <p className="text-sm font-medium text-foreground">No scan runs yet</p>
      <p className="text-xs text-muted-foreground max-w-xs mx-auto">
        The scanner runs every 6 hours via GitHub Actions. Trigger a manual run
        or wait for the next scheduled execution.
      </p>
    </div>
  );
}

function FirstRunInProgress() {
  return (
    <div className="rounded-lg border border-border bg-card p-12 text-center space-y-3">
      <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" />
      <p className="text-sm font-medium text-foreground">
        First scan in progress
      </p>
      <p className="text-xs text-muted-foreground max-w-xs mx-auto">
        Results will appear here once the run completes.
      </p>
    </div>
  );
}

// ── No-candidates banner ──────────────────────────────────────────────────────
// Shown when the most recent finalized run produced zero clean and zero ugly
// candidates. Makes the "—"-vs-"0" distinction explicit so the operator knows
// the scan finished with an empty universe of setups.

function NoCandidatesBanner() {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
      <span className="font-medium text-foreground">
        No candidates produced this run.
      </span>{" "}
      The pipeline finished; no asset met clean or ugly qualification.
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default async function DashboardPage() {
  const { finalizedRun, runningRun, activeAssets } = await getOverviewData();

  // True only when the latest finalized run produced exactly zero clean and
  // zero ugly candidates (explicit 0, not null/unknown).
  const showNoCandidatesBanner =
    !!finalizedRun &&
    finalizedRun.candidates_clean === 0 &&
    finalizedRun.candidates_ugly === 0;

  return (
    <div className="max-w-5xl mx-auto px-8 py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-foreground">Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Latest scanner results and live pipeline status.
        </p>
      </div>

      {/* Live status — only when a scan is running */}
      {runningRun && <CurrentRunStrip run={runningRun} />}

      {/* KPI cards — driven by the latest finalized run */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard
          label="Clean Candidates"
          value={finalizedRun?.candidates_clean ?? "—"}
          sub="latest finalized run"
          Icon={TrendingUp}
          accent="green"
        />
        <StatCard
          label="Ugly Candidates"
          value={finalizedRun?.candidates_ugly ?? "—"}
          sub="latest finalized run"
          Icon={AlertTriangle}
          accent="amber"
        />
        <StatCard
          label="Alerts Sent"
          value={finalizedRun?.alerts_sent ?? "—"}
          sub="latest finalized run"
          Icon={Bell}
        />
        <StatCard
          label="Universe"
          value={activeAssets > 0 ? activeAssets : "—"}
          sub="active USD pairs"
          Icon={Database}
        />
      </div>

      {/* Zero-candidates banner */}
      {showNoCandidatesBanner && <NoCandidatesBanner />}

      {/* Most recent finalized run summary */}
      {finalizedRun ? (
        <FinalizedRunCard run={finalizedRun} />
      ) : runningRun ? (
        <FirstRunInProgress />
      ) : (
        <EmptyState />
      )}
    </div>
  );
}
