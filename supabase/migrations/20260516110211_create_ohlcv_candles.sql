-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: ohlcv_candles
--
-- Persists raw OHLCV candles so validation tooling can detect fills, stop
-- hits, target hits, and MAE/MFE at native timeframe granularity instead of
-- the ~6h close-price approximation available from market_snapshots.
--
-- A candle is an immutable market fact, NOT run-scoped: the scanner re-fetches
-- 250 candles per timeframe every run but only the newest 1–2 are new. The
-- UNIQUE (asset_id, timeframe, candle_timestamp) key makes the persister's
-- upsert a no-op for already-stored candles, so the table grows by only the
-- handful of genuinely new candles per asset per run (deduplicated append).
--
-- Scope: candles are written for hard-filter-passed assets only (the same
-- asset set as market_snapshots / indicator_snapshots).
--
-- No scan_run_id column by design — a candle does not belong to a run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ohlcv_candles (
  id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id         UUID          NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  timeframe        TEXT          NOT NULL,   -- '4h' | '1h' | '30m'
  candle_timestamp TIMESTAMPTZ   NOT NULL,   -- open time of the candle (UTC)

  open             NUMERIC(20,8) NOT NULL,
  high             NUMERIC(20,8) NOT NULL,
  low              NUMERIC(20,8) NOT NULL,
  close            NUMERIC(20,8) NOT NULL,
  volume           NUMERIC(28,8) NOT NULL,   -- base-currency volume for the candle

  created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

  CONSTRAINT ohlcv_candles_unique UNIQUE (asset_id, timeframe, candle_timestamp),
  CONSTRAINT ohlcv_candles_timeframe_check CHECK (
    timeframe IN ('4h', '1h', '30m')
  )
);

-- Forward-path lookups for validation: "all 4h candles for asset X after time T".
CREATE INDEX idx_ohlcv_asset_tf_time
  ON ohlcv_candles (asset_id, timeframe, candle_timestamp DESC);

COMMENT ON TABLE  ohlcv_candles IS
  'Raw OHLCV candles for hard-filter-passed assets. Deduplicated append: each (asset, timeframe, candle_timestamp) stored once. Used by validation tooling.';
COMMENT ON COLUMN ohlcv_candles.candle_timestamp IS
  'Candle open time (UTC). ccxt millisecond timestamps are converted to timestamptz on write.';
COMMENT ON COLUMN ohlcv_candles.volume IS
  'Base-currency volume for the candle (ccxt convention), matching scanner OHLCVCandle.volume.';
