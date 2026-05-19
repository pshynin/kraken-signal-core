import type { Metadata } from "next";
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
import { PageShell, PageHeader } from "@/components/shell/page-shell";
import type { ScanRunRow } from "@kraken-signal/shared-types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Overview" };

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
    <div className="rounded-xl border border-border/70 bg-card p-5 shadow-card transition-colors hover:border-border">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </span>
        <Icon className={`h-4 w-4 ${iconColor}`} />
      </div>
      <p className="mt-3 text-3xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Current run strip ─────────────────────────────────────────────────────────

function CurrentRunStrip({ run }: { run: ScanRunRow }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-primary/25 bg-primary/[0.04] px-4 py-2.5 text-sm">
      <span className="inline-flex items-center gap-1.5 font-medium text-primary">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Running
      </span>
      <span className="text-muted-foreground">
        started {formatRelativeTime(run.started_at)}
      </span>
      <span className="text-muted-foreground/40">·</span>
      <span className="text-muted-foreground capitalize">
        triggered by {run.triggered_by}
      </span>
    </div>
  );
}

// ── Metric cell ──────────────────────────────────────────────────────────────

function Metric({
  label,
  value,
  mono = true,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`mt-1 text-sm font-medium text-foreground ${mono ? "tabular-nums" : "capitalize"}`}
      >
        {value}
      </p>
    </div>
  );
}

// ── Most recent finalized run card ────────────────────────────────────────────

function FinalizedRunCard({ run }: { run: ScanRunRow }) {
  const duration = runDurationSeconds(run);
  return (
    <section className="rounded-xl border border-border/70 bg-card shadow-card">
      <header className="flex items-center justify-between gap-4 border-b border-border/60 px-5 py-4">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Most Recent Finalized Run
        </h2>
        <ScanStatusBadge status={run.status} />
      </header>

      <div className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 sm:grid-cols-4">
        <Metric label="Started" value={formatRelativeTime(run.started_at)} />
        <Metric
          label="Completed"
          value={run.completed_at ? formatRelativeTime(run.completed_at) : "—"}
        />
        <Metric
          label="Duration"
          value={duration != null ? formatDuration(duration) : "—"}
        />
        <Metric label="Triggered by" value={run.triggered_by} mono={false} />
        <Metric label="Assets scanned" value={run.assets_scanned ?? "—"} />
        <Metric label="Passed filter" value={run.assets_passed_filter ?? "—"} />
        <Metric label="Clean candidates" value={run.candidates_clean ?? "—"} />
        <Metric label="Ugly candidates" value={run.candidates_ugly ?? "—"} />
      </div>

      <footer className="flex items-center justify-between border-t border-border/60 px-5 py-3 text-xs">
        <span className="text-muted-foreground">
          Alerts sent{" "}
          <span className="ml-1 font-medium text-foreground tabular-nums">
            {run.alerts_sent ?? "—"}
          </span>
        </span>
        <span className="font-mono text-muted-foreground/60">
          {run.id.slice(0, 8)}
        </span>
      </footer>

      {run.error_message && (
        <p className="mx-5 mb-5 rounded-md bg-bear/10 px-3 py-2 text-xs text-bear font-mono">
          {run.error_message}
        </p>
      )}
    </section>
  );
}

// ── Empty / first-run states ──────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-12 text-center space-y-3 shadow-card">
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
    <div className="rounded-xl border border-border/70 bg-card p-12 text-center space-y-3 shadow-card">
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

function NoCandidatesBanner() {
  return (
    <div className="rounded-xl border border-border/70 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
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

  const showNoCandidatesBanner =
    !!finalizedRun &&
    finalizedRun.candidates_clean === 0 &&
    finalizedRun.candidates_ugly === 0;

  return (
    <PageShell>
      <PageHeader
        title="Overview"
        subtitle="Latest scanner results and live pipeline status."
      />

      {runningRun && <CurrentRunStrip run={runningRun} />}

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

      {showNoCandidatesBanner && <NoCandidatesBanner />}

      {finalizedRun ? (
        <FinalizedRunCard run={finalizedRun} />
      ) : runningRun ? (
        <FirstRunInProgress />
      ) : (
        <EmptyState />
      )}
    </PageShell>
  );
}
