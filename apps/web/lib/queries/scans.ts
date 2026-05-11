/**
 * Supabase queries for the scan history pages (/scans, /scans/[id]).
 */

import type { ScanRunRow } from "@kraken-signal/shared-types";
import { createServerClient } from "@/lib/supabase/server";

/** Scan run list row with derived duration field. */
export interface ScanRunListRow {
  id: string;
  status: string;
  triggered_by: string;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  assets_scanned: number | null;
  assets_passed_filter: number | null;
  candidates_clean: number | null;
  candidates_ugly: number | null;
  alerts_sent: number | null;
  error_message: string | null;
}

function toListRow(raw: ScanRunRow): ScanRunListRow {
  const duration =
    raw.completed_at && raw.started_at
      ? Math.round(
          (new Date(raw.completed_at).getTime() -
            new Date(raw.started_at).getTime()) /
            1000
        )
      : null;
  return {
    id: raw.id,
    status: raw.status,
    triggered_by: raw.triggered_by,
    started_at: raw.started_at,
    completed_at: raw.completed_at,
    duration_seconds: duration,
    assets_scanned: raw.assets_scanned,
    assets_passed_filter: raw.assets_passed_filter,
    candidates_clean: raw.candidates_clean,
    candidates_ugly: raw.candidates_ugly,
    alerts_sent: raw.alerts_sent,
    error_message: raw.error_message,
  };
}

/** Fetch paginated scan run history, newest first. */
export async function fetchScanRuns(
  limit = 50,
  offset = 0
): Promise<ScanRunListRow[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("scan_runs")
      .select(
        "id, status, triggered_by, started_at, completed_at, assets_scanned, assets_passed_filter, candidates_clean, candidates_ugly, alerts_sent, error_message"
      )
      .order("started_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error("fetchScanRuns:", error.message);
      return [];
    }
    return ((data ?? []) as unknown as ScanRunRow[]).map(toListRow);
  } catch (err) {
    console.error("fetchScanRuns exception:", err);
    return [];
  }
}

/** Fetch a single scan run by id. Returns null if not found. */
export async function fetchScanRun(
  id: string
): Promise<ScanRunListRow | null> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("scan_runs")
      .select(
        "id, status, triggered_by, started_at, completed_at, assets_scanned, assets_passed_filter, candidates_clean, candidates_ugly, alerts_sent, error_message"
      )
      .eq("id", id)
      .single();

    if (error || !data) return null;
    return toListRow(data as unknown as ScanRunRow);
  } catch {
    return null;
  }
}

/** Candidate row for a specific scan run detail page. */
export interface ScanCandidateRow {
  id: string;
  symbol: string;
  rank: number;
  category: string;
  score_total: number | null;
  probability_pct: number | null;
  entry_price: number;
  exit_price: number;
  stop_loss: number;
  expected_gain_pct: number | null;
  reward_risk_ratio: number | null;
  suggested_size_bucket: string;
  state: string;
}

interface RawScanCandidate {
  id: string;
  rank: number;
  category: string;
  entry_price: number;
  exit_price: number;
  stop_loss: number;
  expected_gain_pct: number | null;
  reward_risk_ratio: number | null;
  suggested_size_bucket: string;
  state: string;
  assets: { symbol: string } | null;
  candidate_scores: {
    score_total: number | null;
    probability_pct: number | null;
  } | null;
}

/** Fetch all candidates for a specific scan run. */
export async function fetchScanRunCandidates(
  scanRunId: string
): Promise<ScanCandidateRow[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("candidate_recommendations")
      .select(
        `id, rank, category, entry_price, exit_price, stop_loss,
         expected_gain_pct, reward_risk_ratio, suggested_size_bucket, state,
         assets ( symbol ),
         candidate_scores ( score_total, probability_pct )`
      )
      .eq("scan_run_id", scanRunId)
      .order("category", { ascending: true })
      .order("rank", { ascending: true });

    if (error) {
      console.error("fetchScanRunCandidates:", error.message);
      return [];
    }

    return ((data ?? []) as unknown as RawScanCandidate[]).map((r) => ({
      id: r.id,
      symbol: r.assets?.symbol ?? "???",
      rank: r.rank,
      category: r.category,
      score_total: r.candidate_scores?.score_total ?? null,
      probability_pct: r.candidate_scores?.probability_pct ?? null,
      entry_price: r.entry_price,
      exit_price: r.exit_price,
      stop_loss: r.stop_loss,
      expected_gain_pct: r.expected_gain_pct,
      reward_risk_ratio: r.reward_risk_ratio,
      suggested_size_bucket: r.suggested_size_bucket,
      state: r.state,
    }));
  } catch (err) {
    console.error("fetchScanRunCandidates exception:", err);
    return [];
  }
}
