/**
 * Scanner pipeline contracts.
 *
 * These TypeScript interfaces define the data shapes produced and consumed at
 * each stage of the Python scanner pipeline. They serve as:
 *   1. Documentation of inter-stage data contracts.
 *   2. The shape the web app expects when querying scanner output from Supabase.
 *   3. A shared vocabulary that Python dataclasses mirror 1:1.
 *
 * Pipeline stages (PR references):
 *   Universe  (PR 4) → Fetcher   (PR 5) → Indicators (PR 6)
 *   → HardFilter (PR 7) → Scorer (PR 8) → Selector   (PR 9)
 *   → StateMachine (PR 10) → Persister (PR 10) → Alerter (PR 11)
 */

import type { Category, RecommendationCategory, SizeBucket, Timeframe } from "./enums";

// ── PR 4: Universe Loader ─────────────────────────────────────────────────────

/** One tradable asset from the Kraken AssetPairs API, post-filter. */
export interface AssetUniverseItem {
  symbol: string;           // e.g. "SOL"
  kraken_pair: string;      // e.g. "SOLUSDT" or "SOLUSD"
  base_currency: string;
  quote_currency: string;   // always "USD" for MVP
  min_order_size: number;   // from Kraken ordermin field
  lot_decimals: number;     // price decimal places
}

// ── PR 5: Market Data Fetcher ─────────────────────────────────────────────────

/** Single OHLCV candle as returned by ccxt. */
export interface OHLCVCandle {
  timestamp: number;   // Unix ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Multi-timeframe OHLCV bundle for one asset. */
export interface AssetOHLCV {
  asset_id: string;
  symbol: string;
  kraken_pair: string;
  candles_4h: OHLCVCandle[];
  candles_1h: OHLCVCandle[];
  candles_30m: OHLCVCandle[];
  fetched_at: string;        // ISO 8601
}

// ── PR 6: Indicator Engine ────────────────────────────────────────────────────

/** Computed indicators for one asset on one timeframe. */
export interface IndicatorValues {
  asset_id: string;
  timeframe: Timeframe;
  snapshot_time: string;     // ISO 8601 of last closed candle

  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  price_vs_ema20_pct: number | null;
  price_vs_ema50_pct: number | null;
  price_vs_ema200_pct: number | null;

  vwap: number | null;
  price_vs_vwap_pct: number | null;

  rsi_14: number | null;

  atr_14: number | null;
  atr_14_pct: number | null;

  volume_ma_20: number | null;
  volume_current: number | null;

  trend_state: string | null;
  ema_alignment: string | null;
  vwap_state: string | null;
}

/** All three timeframes for one asset, output of the indicator engine. */
export interface AssetIndicators {
  asset_id: string;
  symbol: string;
  tf_4h: IndicatorValues;
  tf_1h: IndicatorValues;
  tf_30m: IndicatorValues;
}

// ── PR 7: Hard Filter + Market Metrics ────────────────────────────────────────

/**
 * Market metrics computed from OHLCV data before scoring.
 * Maps directly to a MarketSnapshotInsert row.
 */
export interface MarketMetrics {
  asset_id: string;
  symbol: string;
  snapshot_time: string;

  price_usd: number;
  price_btc: number | null;

  volume_24h_usd: number | null;
  volume_7d_avg_usd: number | null;
  volume_ratio_20d: number | null;

  return_3d: number | null;
  return_7d: number | null;
  return_14d: number | null;
  return_vs_btc_7d: number | null;

  dist_from_7d_high: number | null;
  dist_from_20d_high: number | null;

  spread_pct: number | null;
  atr_pct_7d: number | null;
}

/**
 * Result of the hard filter stage for one asset.
 * Passed = survives all exclusion rules; Failed = excluded with reason.
 */
export interface HardFilterResult {
  asset_id: string;
  symbol: string;
  passed: boolean;
  exclusion_reason: string | null;
}

// ── PR 8: Scoring Engine ──────────────────────────────────────────────────────

/** Full 9-factor score breakdown for one asset. */
export interface ScoreBreakdown {
  asset_id: string;
  symbol: string;
  category: Category | null;
  exclusion_reason: string | null;

  score_total: number;
  score_liquidity: number;    // /20
  score_upside: number;       // /15
  score_volatility: number;   // /10
  score_structure: number;    // /15
  score_rel_strength: number; // /10
  score_volume: number;       // /10
  score_catalyst: number;     // /10
  score_supply_risk: number;  // /5
  score_execution: number;    // /5

  probability_pct: number | null;
}

// ── PR 9: Candidate Selector + Trade Params ───────────────────────────────────

/** Computed entry/exit/stop/size parameters for one candidate. */
export interface TradeParameters {
  asset_id: string;
  symbol: string;

  entry_price: number;
  entry_price_low: number | null;
  entry_price_high: number | null;
  exit_price: number;
  stop_loss: number;

  suggested_size_bucket: SizeBucket;
  expected_gain_pct: number;
  reward_risk_ratio: number;
  notes: string | null;
}

/** Full scored + parameterized candidate ready for DB persistence. */
export interface ScoredCandidate {
  asset_id: string;
  symbol: string;
  kraken_pair: string;
  category: RecommendationCategory;
  rank: number;

  score: ScoreBreakdown;
  trade: TradeParameters;
  market: MarketMetrics;
  indicators: AssetIndicators;
}

/**
 * A scored candidate that the entry engine could not produce a valid trade
 * plan for. Mirrors scanner.models.EntryRejection.
 *
 * Persisted to asset_state_history with to_state='entry_rejected' and
 * reason set to one of the entry-engine rejection-reason constants
 * (see apps/scanner/scanner/rejection_reasons.py).
 *
 * Distinct from `excluded` (hard-filter failure) and `low_score`
 * (scored below watchlist_min_score): an entry_rejected candidate would
 * have scored well enough for clean/ugly but failed the entry-engine
 * validity gates (e.g. over-chased breakout, no qualified reclaim anchor).
 */
export interface EntryRejection {
  symbol: string;
  category: RecommendationCategory;
  rank: number;
  setup_type: "pullback" | "breakout_trigger" | "reclaim";
  rejection_reason: string;
  metadata: Record<string, unknown>;
}

// ── PR 10: Run persister ──────────────────────────────────────────────────────

/** Summary written back to scan_runs at completion. */
export interface ScanRunFinalStats {
  scan_run_id: string;
  status: "completed" | "failed" | "partial";
  completed_at: string;
  assets_scanned: number;
  assets_passed_filter: number;
  candidates_clean: number;
  candidates_ugly: number;
  alerts_sent: number;
  scanner_version: string | null;
  error_message: string | null;
}

// ── Top-level pipeline input / output ─────────────────────────────────────────

/** Arguments passed to the scanner main() entrypoint. */
export interface ScanInput {
  dry_run: boolean;
  triggered_by: "schedule" | "manual";
  scanner_version: string | null;
}

/** Final output of a complete scan pipeline run. */
export interface ScanOutput {
  scan_run_id: string;
  status: "completed" | "failed" | "partial";
  clean_candidates: ScoredCandidate[];
  ugly_candidates: ScoredCandidate[];
  entry_rejected: EntryRejection[];
  stats: ScanRunFinalStats;
}
