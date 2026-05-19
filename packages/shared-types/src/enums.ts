/**
 * String union types for every enum-like column in the database schema.
 * These match the CHECK constraints in the migrations exactly.
 *
 * Pattern: use the type for type-checking; use the const map when you need
 * runtime access to all valid values (e.g., to populate a select element).
 */

// ── Asset lifecycle state machine ─────────────────────────────────────────────
export type AssetState =
  | "excluded"
  | "watchlist"        // scored at or above watchlist_min_score, not selected
  | "low_score"        // scored below watchlist_min_score
  | "candidate_clean"
  | "candidate_ugly"
  | "entry_rejected"   // selected but the entry engine produced no valid plan
  | "alerted"
  | "active"
  | "invalidated"
  | "expired"
  | "entered"         // future: trade tracking
  | "target_hit"      // future: trade tracking
  | "stop_hit"        // future: trade tracking
  | "manually_closed"; // future: trade tracking

export const ASSET_STATES: Record<AssetState, AssetState> = {
  excluded: "excluded",
  watchlist: "watchlist",
  low_score: "low_score",
  candidate_clean: "candidate_clean",
  candidate_ugly: "candidate_ugly",
  entry_rejected: "entry_rejected",
  alerted: "alerted",
  active: "active",
  invalidated: "invalidated",
  expired: "expired",
  entered: "entered",
  target_hit: "target_hit",
  stop_hit: "stop_hit",
  manually_closed: "manually_closed",
};

/** States that represent an asset still worth monitoring. */
export const ACTIVE_STATES: AssetState[] = [
  "candidate_clean",
  "candidate_ugly",
  "alerted",
  "active",
  "entered",
];

// ── Candidate category (scoring output) ───────────────────────────────────────
export type Category =
  | "clean"
  | "ugly"
  | "excluded"
  | "watchlist"
  | "low_score"; // scored but below watchlist_min_score — distinct from 'excluded'

/** Category values that appear in candidate_recommendations (never 'excluded', 'watchlist', or 'low_score'). */
export type RecommendationCategory = "clean" | "ugly";

// ── Suggested trade size buckets ──────────────────────────────────────────────
// Must stay in sync with apps/scanner/scanner/models.py::SIZE_BUCKETS and the
// crecs_size_bucket_check CHECK constraint in supabase/migrations/.
export type SizeBucket =
  | "2k"
  | "2k-5k"
  | "5k-10k"
  | "10k-20k"
  | "20k-35k"
  | "35k-50k"
  | "50k-100k"
  | "100k+";

export const SIZE_BUCKETS: SizeBucket[] = [
  "2k",
  "2k-5k",
  "5k-10k",
  "10k-20k",
  "20k-35k",
  "35k-50k",
  "50k-100k",
  "100k+",
];

// ── Multi-timeframe analysis ───────────────────────────────────────────────────
export type Timeframe = "4h" | "1h" | "30m";

export const TIMEFRAMES: Timeframe[] = ["4h", "1h", "30m"];

// ── Scan run lifecycle ────────────────────────────────────────────────────────
// Mirrors the scan_runs_status_check / scan_runs_triggered_by_check constraints
// (migration 0015 added 'timed_out' and 'ci').
export type ScanStatus =
  | "running"
  | "completed"
  | "failed"
  | "partial"
  | "timed_out";

export type ScanTrigger = "schedule" | "manual" | "ci";

// ── Alert types ────────────────────────────────────────────────────────────────
export type AlertType =
  | "new_candidate"
  | "state_change"
  | "expiry_warning"
  | "invalidation"
  | "system";

// ── Discord delivery channels ─────────────────────────────────────────────────
export type AlertChannel = "discord_clean" | "discord_ugly" | "discord_system";

// ── Alert delivery status ─────────────────────────────────────────────────────
export type AlertDeliveryStatus = "pending" | "sent" | "failed";

// ── Indicator-derived state classifications ───────────────────────────────────

/** EMA 200 slope + price position relative to EMA20/50/200. */
export type TrendState = "strong_up" | "up" | "neutral" | "down" | "strong_down";

/** Relative ordering of price vs EMA20, EMA50, EMA200. */
export type EmaAlignment = "bullish" | "partial_bullish" | "neutral" | "bearish";

/**
 * Price position relative to VWAP.
 * - above:      price > VWAP by >0.5%
 * - reclaiming: price crossed VWAP in last 3 candles
 * - below:      all other
 */
export type VwapState = "above" | "reclaiming" | "below";
