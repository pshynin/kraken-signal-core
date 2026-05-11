import {
  TrendingUp,
  AlertTriangle,
  Bell,
  Database,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { createServerClient } from "@/lib/supabase/server";
import { formatRelativeTime } from "@/lib/utils";
import type { ScanRunRow } from "@kraken-signal/shared-types";

// ── Data fetching ─────────────────────────────────────────────────────────────

async function getOverviewData(): Promise<{
  lastRun: ScanRunRow | null;
  activeAssets: number;
}> {
  try {
    const client = createServerClient();
    const [runRes, assetRes] = await Promise.all([
      client
        .from("scan_runs")
        .select("*")
        .order("started_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
      client
        .from("assets")
        .select("*", { count: "exact", head: true })
        .eq("is_active", true),
    ]);
    return {
      lastRun: (runRes.data as ScanRunRow | null) ?? null,
      activeAssets: assetRes.count ?? 0,
    };
  } catch {
    return { lastRun: null, activeAssets: 0 };
  }
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string; Icon: React.ElementType }> = {
    completed: {
      label: "Completed",
      className: "text-bull bg-bull/10",
      Icon: CheckCircle2,
    },
    running: {
      label: "Running",
      className: "text-primary bg-primary/10",
      Icon: Loader2,
    },
    partial: {
      label: "Partial",
      className: "text-caution bg-caution/10",
      Icon: AlertCircle,
    },
    failed: {
      label: "Failed",
      className: "text-bear bg-bear/10",
      Icon: XCircle,
    },
  };
  const cfg = map[status] ?? map.failed;
  const { label, className, Icon } = cfg;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
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

// ── Last run detail row ───────────────────────────────────────────────────────

function LastRunCard({ run }: { run: ScanRunRow }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium text-foreground">Last Scan Run</h2>
          <p className="mt-0.5 text-xs text-muted-foreground font-mono">
            {run.id.slice(0, 8)}…
          </p>
        </div>
        <StatusBadge status={run.status} />
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Started</p>
          <p className="mt-0.5 font-medium text-foreground tabular-nums">
            {formatRelativeTime(run.started_at)}
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
          <p className="text-xs text-muted-foreground">Triggered by</p>
          <p className="mt-0.5 font-medium text-foreground capitalize">
            {run.triggered_by}
          </p>
        </div>
      </div>

      {run.error_message && (
        <p className="rounded-md bg-bear/10 px-3 py-2 text-xs text-bear font-mono">
          {run.error_message}
        </p>
      )}
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

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

// ── Page ──────────────────────────────────────────────────────────────────────

export default async function DashboardPage() {
  const { lastRun, activeAssets } = await getOverviewData();

  return (
    <div className="max-w-5xl mx-auto px-8 py-8 space-y-8">
          {/* Header */}
          <div>
            <h1 className="text-xl font-semibold text-foreground">Overview</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Scanner pipeline status and latest run summary.
            </p>
          </div>

          {/* Stat cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              label="Clean Candidates"
              value={lastRun?.candidates_clean ?? "—"}
              sub="latest run"
              Icon={TrendingUp}
              accent="green"
            />
            <StatCard
              label="Ugly Candidates"
              value={lastRun?.candidates_ugly ?? "—"}
              sub="latest run"
              Icon={AlertTriangle}
              accent="amber"
            />
            <StatCard
              label="Alerts Sent"
              value={lastRun?.alerts_sent ?? "—"}
              sub="latest run"
              Icon={Bell}
            />
            <StatCard
              label="Universe"
              value={activeAssets > 0 ? activeAssets : "—"}
              sub="active USD pairs"
              Icon={Database}
            />
          </div>

          {/* Last run detail */}
          {lastRun ? <LastRunCard run={lastRun} /> : <EmptyState />}
    </div>
  );
}
