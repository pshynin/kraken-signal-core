/**
 * Typed domain models derived from the raw database types.
 *
 * - StrategySettings: strongly-typed mirror of the strategy_settings JSONB rows.
 *   The scanner reads all settings at startup and validates them against this shape.
 *   The web /settings page reads and writes through this model.
 *
 * - Dashboard composite types: join-heavy shapes used by the dashboard pages,
 *   defined here so scanner and web agree on the structure.
 */

import type {
  AssetRow,
  CandidateRecommendationRow,
  CandidateScoreRow,
  MarketSnapshotRow,
  ScanRunRow,
} from "./database";
import type { RecommendationCategory } from "./enums";

// ── StrategySettings: typed view of the strategy_settings table ───────────────
// Each nested object maps to a setting_key prefix in the DB.

export interface CleanThresholds {
  /** Minimum total score (0–100). Default: 70 */
  min_score: number;
  /** 7-day average dollar volume floor. Default: $5M */
  min_volume_7d_avg_usd: number;
  /** 24-hour dollar volume floor. Default: $2M */
  min_volume_24h_usd: number;
  /** ATR 7d minimum as % of price. Default: 4.0 */
  min_atr_pct: number;
  /** ATR 7d maximum as % of price. Default: 18.0 */
  max_atr_pct: number;
  /** Max 3-day return before anti-chase rejection. Default: 0.30 (+30%) */
  max_return_3d: number;
  /** Max % price can be above EMA20 (anti-chase). Default: 12.0 */
  max_price_vs_ema20_pct: number;
  /** Min volume ratio vs 20-day average. Default: 1.2 */
  min_volume_ratio: number;
  /** Require positive 7-day relative strength vs BTC. Default: true */
  require_positive_rs_btc: boolean;
  /** Entry zone must be within this % of current price. Default: 5.0 */
  max_entry_distance_pct: number;
  /** Minimum reward/risk ratio. Default: 2.0 */
  min_reward_risk: number;
  /** Preferred RSI lower bound. Default: 52 */
  rsi_preferred_min: number;
  /** Preferred RSI upper bound. Default: 68 */
  rsi_preferred_max: number;
}

export interface UglyThresholds {
  /** Minimum total score (0–100). Default: 62 */
  min_score: number;
  /** 7-day average dollar volume floor. Default: $750k */
  min_volume_7d_avg_usd: number;
  /** 24-hour dollar volume floor. Default: $300k */
  min_volume_24h_usd: number;
  /** ATR 7d minimum as % of price. Default: 6.0 */
  min_atr_pct: number;
  /** ATR 7d maximum as % of price. Default: 30.0 */
  max_atr_pct: number;
  /** Max 3-day return before anti-chase rejection. Default: 0.40 (+40%) */
  max_return_3d: number;
  /** Max % price can be above EMA20 (anti-chase). Default: 20.0 */
  max_price_vs_ema20_pct: number;
  /** Min volume ratio vs 20-day average. Default: 1.3 */
  min_volume_ratio: number;
  /** Minimum stop distance % from entry. Default: 8.0 */
  min_stop_pct: number;
  /** Maximum stop distance % from entry. Default: 15.0 */
  max_stop_pct: number;
  /** Minimum reward/risk ratio. Default: 2.5 */
  min_reward_risk: number;
  /** Preferred RSI lower bound. Default: 50 */
  rsi_preferred_min: number;
  /** Preferred RSI upper bound. Default: 72 */
  rsi_preferred_max: number;
}

export interface GlobalThresholds {
  /** RSI below this → hard exclude. Default: 48 */
  rsi_hard_min: number;
  /** RSI above this → exclude or penalize. Default: 78 */
  rsi_hard_max: number;
}

export interface ScannerConfig {
  /** Max candidates in the clean output table. Default: 10 */
  max_clean_candidates: number;
  /** Max candidates in the ugly output table. Default: 10 */
  max_ugly_candidates: number;
  /**
   * New candidate must outscore an existing top-N entry by at least this
   * much to rotate it out (stability rule). Default: 3.0
   */
  min_score_delta_for_rotation: number;
  /** Hours before re-alerting same asset + alert_type. Default: 8 */
  alert_dedup_hours: number;
  /** Hours since last successful run before system alert fires. Default: 6 */
  stale_run_threshold_hours: number;
  /** Minimum practical trade size in USD. Default: 2000 */
  min_trade_size_usd: number;
}

export interface SizeBucketCondition {
  min_score: number;
  min_volume_7d_avg_usd?: number;
}

export interface SizingThresholds {
  clean_20k_plus: SizeBucketCondition;
  clean_10k_20k: SizeBucketCondition;
  clean_5k_10k: SizeBucketCondition;
  ugly_5k_10k: SizeBucketCondition;
  ugly_2k_5k: SizeBucketCondition;
}

export interface ScoringConfig {
  /**
   * Maps score floor (as string key) to heuristic probability percentile.
   * Example: { "85": 90.0, "78": 84.0, "70": 77.0, "62": 69.0 }
   */
  probability_map: Record<string, number>;
}

/** Fully typed view of all strategy_settings rows, grouped by prefix. */
export interface StrategySettings {
  clean: CleanThresholds;
  ugly: UglyThresholds;
  global: GlobalThresholds;
  scanner: ScannerConfig;
  sizing: SizingThresholds;
  scoring: ScoringConfig;
}

// ── Dashboard composite types ─────────────────────────────────────────────────
// These shapes are used by Next.js server components and route handlers.
// They represent common join patterns against the Supabase DB.

/** Full candidate card as shown in the dashboard table. */
export interface CandidateCard {
  recommendation: CandidateRecommendationRow;
  score: CandidateScoreRow;
  asset: AssetRow;
  market: MarketSnapshotRow | null;
}

/** Scan run summary with candidate counts for the /scans history page. */
export interface ScanRunSummary {
  run: ScanRunRow;
  candidate_count_clean: number;
  candidate_count_ugly: number;
  alert_count: number;
}

/** Grouped candidates for the main dashboard view. */
export interface DashboardData {
  latest_run: ScanRunRow | null;
  clean: CandidateCard[];
  ugly: CandidateCard[];
  last_updated: string;
}

/** Per-category table row as rendered by the dashboard table component. */
export interface CandidateTableRow {
  id: string;
  asset_id: string;
  symbol: string;
  rank: number;
  category: RecommendationCategory;
  score_total: number;
  probability_pct: number | null;
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
  scanned_at: string;
  market_price_at_scan: number | null;
  distance_to_entry_pct: number | null;
}
