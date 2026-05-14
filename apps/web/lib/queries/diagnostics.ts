/**
 * Supabase queries for diagnostics surfaces (PR 25):
 *   - /scans/[id] adds panels for exclusions, entry rejections, and
 *     watchlist/low_score counts derived from asset_state_history rows
 *     written by the persister and state machine.
 *   - /assets/[symbol] reads the full per-asset state-transition timeline.
 *
 * All shapes are dashboard-internal; not promoted to packages/shared-types.
 */

import { createServerClient } from "@/lib/supabase/server";

// ── Run-level diagnostics ────────────────────────────────────────────────────

/** Aggregated count of hard-filter exclusions by reason for one run. */
export interface ExclusionCount {
  reason: string;
  count: number;
}

/** Single entry-engine rejection: the candidate the engine refused to plan. */
export interface EntryRejectionRow {
  symbol: string;
  setup_type: string;
  rejection_reason: string;
  current_price: number | null;
  score_total: number | null;
}

/** Watchlist + low_score totals for one run. Counts only by design (PR 25). */
export interface CategoryBreakdown {
  watchlist: number;
  low_score: number;
}

interface RawExclusionRow {
  reason: string | null;
}

/**
 * Count hard-filter exclusions for a single scan run, grouped by reason.
 * Returns rows sorted descending by count.
 */
export async function fetchRunExclusions(
  scanRunId: string
): Promise<ExclusionCount[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("asset_state_history")
      .select("reason")
      .eq("scan_run_id", scanRunId)
      .eq("to_state", "excluded");

    if (error) {
      console.error("fetchRunExclusions:", error.message);
      return [];
    }

    const counts = new Map<string, number>();
    for (const row of (data ?? []) as RawExclusionRow[]) {
      const r = row.reason ?? "unknown";
      counts.set(r, (counts.get(r) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count);
  } catch (err) {
    console.error("fetchRunExclusions exception:", err);
    return [];
  }
}

interface RawEntryRejectionRow {
  reason: string | null;
  metadata: {
    setup_type?: string;
    current_price?: number;
    score_total?: number;
  } | null;
  assets: { symbol: string } | null;
}

/**
 * Fetch per-candidate entry-engine rejections for one run. Each row was
 * a scored clean/ugly candidate that the selector or entry engine dropped
 * because no valid trade plan could be constructed.
 */
export async function fetchRunEntryRejections(
  scanRunId: string
): Promise<EntryRejectionRow[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("asset_state_history")
      .select("reason, metadata, assets ( symbol )")
      .eq("scan_run_id", scanRunId)
      .eq("to_state", "entry_rejected");

    if (error) {
      console.error("fetchRunEntryRejections:", error.message);
      return [];
    }

    return ((data ?? []) as unknown as RawEntryRejectionRow[]).map((row) => ({
      symbol: row.assets?.symbol ?? "???",
      setup_type: row.metadata?.setup_type ?? "—",
      rejection_reason: row.reason ?? "unknown",
      current_price: row.metadata?.current_price ?? null,
      score_total: row.metadata?.score_total ?? null,
    }));
  } catch (err) {
    console.error("fetchRunEntryRejections exception:", err);
    return [];
  }
}

/**
 * Count watchlist + low_score transitions for one run. Counts only —
 * full lists would be too noisy on the diagnostics panel.
 */
export async function fetchRunCategoryBreakdown(
  scanRunId: string
): Promise<CategoryBreakdown> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("asset_state_history")
      .select("to_state")
      .eq("scan_run_id", scanRunId)
      .in("to_state", ["watchlist", "low_score"]);

    if (error) {
      console.error("fetchRunCategoryBreakdown:", error.message);
      return { watchlist: 0, low_score: 0 };
    }

    let watchlist = 0;
    let low_score = 0;
    for (const row of (data ?? []) as { to_state: string }[]) {
      if (row.to_state === "watchlist") watchlist += 1;
      else if (row.to_state === "low_score") low_score += 1;
    }
    return { watchlist, low_score };
  } catch (err) {
    console.error("fetchRunCategoryBreakdown exception:", err);
    return { watchlist: 0, low_score: 0 };
  }
}

// ── Per-asset history ────────────────────────────────────────────────────────

/** One row of an asset's state-transition timeline. */
export interface AssetHistoryRow {
  created_at: string;
  scan_run_id: string | null;
  from_state: string | null;
  to_state: string;
  reason: string | null;
  metadata: Record<string, unknown> | null;
}

/** Resolution result for /assets/[symbol]: the asset plus its recent history. */
export interface AssetHistoryView {
  symbol: string;
  asset_id: string;
  is_active: boolean;
  history: AssetHistoryRow[];
}

interface RawAssetRow {
  id: string;
  symbol: string;
  is_active: boolean;
}

interface RawHistoryRow {
  created_at: string;
  scan_run_id: string | null;
  from_state: string | null;
  to_state: string;
  reason: string | null;
  metadata: Record<string, unknown> | null;
}

/**
 * Fetch one asset's recent state-transition history.
 *
 * Two-step query (the URL param is the human-readable symbol but
 * asset_state_history keys on asset_id). Returns null if no such symbol
 * exists; returns the view with an empty `history` array if the symbol
 * is known but has no transitions recorded.
 */
export async function fetchAssetHistory(
  symbol: string,
  limit = 100
): Promise<AssetHistoryView | null> {
  try {
    const client = createServerClient();

    const assetResp = await client
      .from("assets")
      .select("id, symbol, is_active")
      .eq("symbol", symbol)
      .maybeSingle();

    if (assetResp.error) {
      console.error("fetchAssetHistory (asset lookup):", assetResp.error.message);
      return null;
    }
    if (!assetResp.data) return null;

    const asset = assetResp.data as RawAssetRow;

    const histResp = await client
      .from("asset_state_history")
      .select("created_at, scan_run_id, from_state, to_state, reason, metadata")
      .eq("asset_id", asset.id)
      .order("created_at", { ascending: false })
      .limit(limit);

    if (histResp.error) {
      console.error("fetchAssetHistory (history):", histResp.error.message);
      return {
        symbol: asset.symbol,
        asset_id: asset.id,
        is_active: asset.is_active,
        history: [],
      };
    }

    return {
      symbol: asset.symbol,
      asset_id: asset.id,
      is_active: asset.is_active,
      history: ((histResp.data ?? []) as RawHistoryRow[]).map((r) => ({
        created_at: r.created_at,
        scan_run_id: r.scan_run_id,
        from_state: r.from_state,
        to_state: r.to_state,
        reason: r.reason,
        metadata: r.metadata,
      })),
    };
  } catch (err) {
    console.error("fetchAssetHistory exception:", err);
    return null;
  }
}
