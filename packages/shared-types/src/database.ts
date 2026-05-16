/**
 * Supabase Database type — hand-maintained mirror of the SQL migrations.
 *
 * Naming conventions:
 *   Row    — shape returned by a SELECT (all columns present, nullables are T | null)
 *   Insert — shape accepted by an INSERT (generated/defaulted fields are optional)
 *   Update — partial Row used for UPDATE (every field optional)
 *
 * NUMERIC columns in PostgreSQL → `number` in TypeScript.
 * TIMESTAMPTZ columns → `string` (ISO 8601 from Supabase PostgREST).
 * UUID columns → `string`.
 * JSONB columns → `Json`.
 * TEXT[] columns → `string[]`.
 *
 * Update this file whenever a migration changes the schema.
 */

import type {
  AlertChannel,
  AlertDeliveryStatus,
  AlertType,
  AssetState,
  Category,
  EmaAlignment,
  RecommendationCategory,
  SizeBucket,
  ScanStatus,
  ScanTrigger,
  Timeframe,
  TrendState,
  VwapState,
} from "./enums";

/** Generic JSON value — mirrors Supabase's own Json type. */
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json }
  | Json[];

// ── assets ────────────────────────────────────────────────────────────────────

export interface AssetRow {
  id: string;
  symbol: string;
  kraken_pair: string;
  base_currency: string;
  quote_currency: string;
  is_active: boolean;
  excluded_reason: string | null;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface AssetInsert {
  id?: string;
  symbol: string;
  kraken_pair: string;
  base_currency: string;
  quote_currency?: string;
  is_active?: boolean;
  excluded_reason?: string | null;
  first_seen_at?: string;
  last_seen_at?: string;
  created_at?: string;
  updated_at?: string;
}

export type AssetUpdate = Partial<AssetInsert>;

// ── scan_runs ─────────────────────────────────────────────────────────────────

export interface ScanRunRow {
  id: string;
  started_at: string;
  completed_at: string | null;
  status: ScanStatus;
  triggered_by: ScanTrigger;
  assets_scanned: number | null;
  assets_passed_filter: number | null;
  candidates_clean: number | null;
  candidates_ugly: number | null;
  alerts_sent: number | null;
  scanner_version: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ScanRunInsert {
  id?: string;
  started_at: string;
  completed_at?: string | null;
  status?: ScanStatus;
  triggered_by?: ScanTrigger;
  assets_scanned?: number | null;
  assets_passed_filter?: number | null;
  candidates_clean?: number | null;
  candidates_ugly?: number | null;
  alerts_sent?: number | null;
  scanner_version?: string | null;
  error_message?: string | null;
  created_at?: string;
}

export type ScanRunUpdate = Partial<ScanRunInsert>;

// ── market_snapshots ──────────────────────────────────────────────────────────

export interface MarketSnapshotRow {
  id: string;
  scan_run_id: string;
  asset_id: string;
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
  created_at: string;
}

export interface MarketSnapshotInsert {
  id?: string;
  scan_run_id: string;
  asset_id: string;
  snapshot_time: string;
  price_usd: number;
  price_btc?: number | null;
  volume_24h_usd?: number | null;
  volume_7d_avg_usd?: number | null;
  volume_ratio_20d?: number | null;
  return_3d?: number | null;
  return_7d?: number | null;
  return_14d?: number | null;
  return_vs_btc_7d?: number | null;
  dist_from_7d_high?: number | null;
  dist_from_20d_high?: number | null;
  spread_pct?: number | null;
  atr_pct_7d?: number | null;
  created_at?: string;
}

export type MarketSnapshotUpdate = Partial<MarketSnapshotInsert>;

// ── indicator_snapshots ───────────────────────────────────────────────────────

export interface IndicatorSnapshotRow {
  id: string;
  scan_run_id: string;
  asset_id: string;
  timeframe: Timeframe;
  snapshot_time: string;
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
  trend_state: TrendState | null;
  ema_alignment: EmaAlignment | null;
  vwap_state: VwapState | null;
  created_at: string;
}

export interface IndicatorSnapshotInsert {
  id?: string;
  scan_run_id: string;
  asset_id: string;
  timeframe: Timeframe;
  snapshot_time: string;
  ema_20?: number | null;
  ema_50?: number | null;
  ema_200?: number | null;
  price_vs_ema20_pct?: number | null;
  price_vs_ema50_pct?: number | null;
  price_vs_ema200_pct?: number | null;
  vwap?: number | null;
  price_vs_vwap_pct?: number | null;
  rsi_14?: number | null;
  atr_14?: number | null;
  atr_14_pct?: number | null;
  volume_ma_20?: number | null;
  volume_current?: number | null;
  trend_state?: TrendState | null;
  ema_alignment?: EmaAlignment | null;
  vwap_state?: VwapState | null;
  created_at?: string;
}

export type IndicatorSnapshotUpdate = Partial<IndicatorSnapshotInsert>;

// ── ohlcv_candles ─────────────────────────────────────────────────────────────
// Raw OHLCV candles for hard-filter-passed assets. Deduplicated append:
// UNIQUE (asset_id, timeframe, candle_timestamp). Not run-scoped — a candle
// is a market fact, not a property of the run that fetched it. Used by
// validation tooling. Mirrors scanner OHLCVCandle (models.py).

export interface OhlcvCandleRow {
  id: string;
  asset_id: string;
  timeframe: Timeframe;
  candle_timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  created_at: string;
}

export interface OhlcvCandleInsert {
  id?: string;
  asset_id: string;
  timeframe: Timeframe;
  candle_timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  created_at?: string;
}

export type OhlcvCandleUpdate = Partial<OhlcvCandleInsert>;

// ── candidate_scores ──────────────────────────────────────────────────────────

export interface CandidateScoreRow {
  id: string;
  scan_run_id: string;
  asset_id: string;
  category: Category | null;
  exclusion_reason: string | null;
  score_total: number | null;
  score_liquidity: number | null;
  score_upside: number | null;
  score_volatility: number | null;
  score_structure: number | null;
  score_rel_strength: number | null;
  score_volume: number | null;
  score_catalyst: number | null;
  score_supply_risk: number | null;
  score_execution: number | null;
  probability_pct: number | null;
  rank_in_category: number | null;
  created_at: string;
}

export interface CandidateScoreInsert {
  id?: string;
  scan_run_id: string;
  asset_id: string;
  category?: Category | null;
  exclusion_reason?: string | null;
  score_total?: number | null;
  score_liquidity?: number | null;
  score_upside?: number | null;
  score_volatility?: number | null;
  score_structure?: number | null;
  score_rel_strength?: number | null;
  score_volume?: number | null;
  score_catalyst?: number | null;
  score_supply_risk?: number | null;
  score_execution?: number | null;
  probability_pct?: number | null;
  rank_in_category?: number | null;
  created_at?: string;
}

export type CandidateScoreUpdate = Partial<CandidateScoreInsert>;

// ── candidate_recommendations ─────────────────────────────────────────────────

export interface CandidateRecommendationRow {
  id: string;
  scan_run_id: string;
  asset_id: string;
  score_id: string;
  category: RecommendationCategory;
  rank: number;
  entry_price: number;
  entry_price_low: number | null;
  entry_price_high: number | null;
  exit_price: number;
  stop_loss: number;
  suggested_size_bucket: SizeBucket;
  probability_pct: number | null;
  expected_gain_pct: number | null;
  reward_risk_ratio: number | null;
  notes: string | null;
  state: AssetState;
  created_at: string;
  updated_at: string;
}

export interface CandidateRecommendationInsert {
  id?: string;
  scan_run_id: string;
  asset_id: string;
  score_id: string;
  category: RecommendationCategory;
  rank: number;
  entry_price: number;
  entry_price_low?: number | null;
  entry_price_high?: number | null;
  exit_price: number;
  stop_loss: number;
  suggested_size_bucket: SizeBucket;
  probability_pct?: number | null;
  expected_gain_pct?: number | null;
  reward_risk_ratio?: number | null;
  notes?: string | null;
  state?: AssetState;
  created_at?: string;
  updated_at?: string;
}

export type CandidateRecommendationUpdate = Partial<CandidateRecommendationInsert>;

// ── alerts_sent ───────────────────────────────────────────────────────────────

export interface AlertSentRow {
  id: string;
  scan_run_id: string;
  recommendation_id: string | null;
  asset_id: string;
  alert_type: AlertType;
  channel: AlertChannel;
  webhook_url_hash: string;
  payload: Json;
  delivery_status: AlertDeliveryStatus;
  sent_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface AlertSentInsert {
  id?: string;
  scan_run_id: string;
  recommendation_id?: string | null;
  asset_id: string;
  alert_type: AlertType;
  channel: AlertChannel;
  webhook_url_hash: string;
  payload: Json;
  delivery_status?: AlertDeliveryStatus;
  sent_at?: string | null;
  error_message?: string | null;
  created_at?: string;
}

export type AlertSentUpdate = Partial<AlertSentInsert>;

// ── asset_state_history ───────────────────────────────────────────────────────

export interface AssetStateHistoryRow {
  id: string;
  asset_id: string;
  scan_run_id: string | null;
  from_state: AssetState | null;
  to_state: AssetState;
  reason: string | null;
  metadata: Json | null;
  created_at: string;
}

export interface AssetStateHistoryInsert {
  id?: string;
  asset_id: string;
  scan_run_id?: string | null;
  from_state?: AssetState | null;
  to_state: AssetState;
  reason?: string | null;
  metadata?: Json | null;
  created_at?: string;
}

// asset_state_history is immutable — no Update type by design.

// ── strategy_settings ─────────────────────────────────────────────────────────

export interface StrategySettingRow {
  id: string;
  setting_key: string;
  setting_value: Json;
  description: string | null;
  updated_at: string;
  created_at: string;
}

export interface StrategySettingInsert {
  id?: string;
  setting_key: string;
  setting_value: Json;
  description?: string | null;
  updated_at?: string;
  created_at?: string;
}

export type StrategySettingUpdate = Partial<StrategySettingInsert>;

// ── webhook_destinations ──────────────────────────────────────────────────────

export interface WebhookDestinationRow {
  id: string;
  name: string;
  channel_type: string;
  is_active: boolean;
  alert_types: string[];
  created_at: string;
  updated_at: string;
}

export interface WebhookDestinationInsert {
  id?: string;
  name: string;
  channel_type?: string;
  is_active?: boolean;
  alert_types: string[];
  created_at?: string;
  updated_at?: string;
}

export type WebhookDestinationUpdate = Partial<WebhookDestinationInsert>;

// ── Supabase Database type ────────────────────────────────────────────────────
// Used to type the Supabase client: createClient<Database>(url, key)

export type Database = {
  public: {
    Tables: {
      assets: {
        Row: AssetRow;
        Insert: AssetInsert;
        Update: AssetUpdate;
      };
      scan_runs: {
        Row: ScanRunRow;
        Insert: ScanRunInsert;
        Update: ScanRunUpdate;
      };
      market_snapshots: {
        Row: MarketSnapshotRow;
        Insert: MarketSnapshotInsert;
        Update: MarketSnapshotUpdate;
      };
      indicator_snapshots: {
        Row: IndicatorSnapshotRow;
        Insert: IndicatorSnapshotInsert;
        Update: IndicatorSnapshotUpdate;
      };
      ohlcv_candles: {
        Row: OhlcvCandleRow;
        Insert: OhlcvCandleInsert;
        Update: OhlcvCandleUpdate;
      };
      candidate_scores: {
        Row: CandidateScoreRow;
        Insert: CandidateScoreInsert;
        Update: CandidateScoreUpdate;
      };
      candidate_recommendations: {
        Row: CandidateRecommendationRow;
        Insert: CandidateRecommendationInsert;
        Update: CandidateRecommendationUpdate;
      };
      alerts_sent: {
        Row: AlertSentRow;
        Insert: AlertSentInsert;
        Update: AlertSentUpdate;
      };
      asset_state_history: {
        Row: AssetStateHistoryRow;
        Insert: AssetStateHistoryInsert;
        Update: never;
      };
      strategy_settings: {
        Row: StrategySettingRow;
        Insert: StrategySettingInsert;
        Update: StrategySettingUpdate;
      };
      webhook_destinations: {
        Row: WebhookDestinationRow;
        Insert: WebhookDestinationInsert;
        Update: WebhookDestinationUpdate;
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
  };
};
