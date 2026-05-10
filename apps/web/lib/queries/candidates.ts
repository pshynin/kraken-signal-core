/**
 * Supabase query for the candidates dashboard page.
 *
 * Fetches all candidate_recommendations in active states, joining
 * assets (symbol) and candidate_scores (score_total, probability_pct).
 * Maps the raw nested Supabase result to the CandidateTableRow shape
 * defined in @kraken-signal/shared-types.
 */

import type { CandidateTableRow } from "@kraken-signal/shared-types";
import { createServerClient } from "@/lib/supabase/server";

/** States worth showing on the dashboard. */
const ACTIVE_STATES = [
  "candidate_clean",
  "candidate_ugly",
  "alerted",
  "active",
] as const;

/**
 * Raw shape returned by the Supabase join query before mapping.
 * Supabase nests FK selects as objects — typed explicitly here because
 * the Database type does not carry FK relationship metadata.
 */
interface RawRow {
  id: string;
  asset_id: string;
  rank: number;
  category: "clean" | "ugly";
  entry_price: number;
  entry_price_low: number | null;
  entry_price_high: number | null;
  exit_price: number;
  stop_loss: number;
  expected_gain_pct: number | null;
  reward_risk_ratio: number | null;
  suggested_size_bucket: string;
  notes: string | null;
  state: string;
  created_at: string;
  assets: { symbol: string } | null;
  candidate_scores: {
    score_total: number | null;
    probability_pct: number | null;
  } | null;
}

function toTableRow(raw: RawRow): CandidateTableRow {
  return {
    id: raw.id,
    asset_id: raw.asset_id,
    symbol: raw.assets?.symbol ?? "???",
    rank: raw.rank,
    category: raw.category,
    score_total: raw.candidate_scores?.score_total ?? 0,
    probability_pct: raw.candidate_scores?.probability_pct ?? null,
    entry_price: raw.entry_price,
    entry_price_low: raw.entry_price_low,
    entry_price_high: raw.entry_price_high,
    exit_price: raw.exit_price,
    stop_loss: raw.stop_loss,
    expected_gain_pct: raw.expected_gain_pct,
    reward_risk_ratio: raw.reward_risk_ratio,
    suggested_size_bucket: raw.suggested_size_bucket,
    notes: raw.notes,
    state: raw.state,
    scanned_at: raw.created_at,
  };
}

/**
 * Returns all active candidates sorted by category then rank.
 * Returns [] on any error (network, missing env vars, DB error).
 */
export async function fetchActiveCandidates(): Promise<CandidateTableRow[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("candidate_recommendations")
      .select(
        `
        id, asset_id, rank, category,
        entry_price, entry_price_low, entry_price_high,
        exit_price, stop_loss, expected_gain_pct, reward_risk_ratio,
        suggested_size_bucket, notes, state, created_at,
        assets ( symbol ),
        candidate_scores ( score_total, probability_pct )
        `
      )
      .in("state", ACTIVE_STATES)
      .order("category", { ascending: true })
      .order("rank", { ascending: true });

    if (error) {
      console.error("fetchActiveCandidates:", error.message);
      return [];
    }

    return ((data ?? []) as unknown as RawRow[]).map(toTableRow);
  } catch (err) {
    console.error("fetchActiveCandidates exception:", err);
    return [];
  }
}
