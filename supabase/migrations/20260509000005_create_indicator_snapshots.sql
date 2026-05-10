-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0005: indicator_snapshots
-- Per-asset per-scan per-timeframe indicator values.
-- Three rows per asset per run: 4h, 1h, 30m.
-- Retention guidance: 90 days.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE indicator_snapshots (
  id                   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id          UUID          NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  asset_id             UUID          NOT NULL REFERENCES assets(id)    ON DELETE RESTRICT,
  timeframe            TEXT          NOT NULL,   -- '4h' | '1h' | '30m'
  snapshot_time        TIMESTAMPTZ   NOT NULL,   -- timestamp of the most recent closed candle

  -- ── EMAs ───────────────────────────────────────────────────────────────────
  ema_20               NUMERIC(20,8),
  ema_50               NUMERIC(20,8),
  ema_200              NUMERIC(20,8),

  -- ── Price vs EMA distances (positive = above, negative = below) ────────────
  price_vs_ema20_pct   NUMERIC(8,4),            -- e.g. 0.05 = 5% above EMA20
  price_vs_ema50_pct   NUMERIC(8,4),
  price_vs_ema200_pct  NUMERIC(8,4),

  -- ── VWAP (rolling 24h, anchored to UTC midnight for consistency) ───────────
  vwap                 NUMERIC(20,8),
  price_vs_vwap_pct    NUMERIC(8,4),            -- positive = above VWAP

  -- ── RSI ────────────────────────────────────────────────────────────────────
  rsi_14               NUMERIC(6,2),            -- 0–100

  -- ── ATR ────────────────────────────────────────────────────────────────────
  atr_14               NUMERIC(20,8),           -- absolute ATR value in USD
  atr_14_pct           NUMERIC(8,4),            -- ATR as % of current price

  -- ── Volume ─────────────────────────────────────────────────────────────────
  volume_ma_20         NUMERIC(20,4),           -- 20-candle volume moving average
  volume_current       NUMERIC(20,4),           -- last closed candle volume

  -- ── Derived state classifications ──────────────────────────────────────────
  trend_state          TEXT,   -- strong_up | up | neutral | down | strong_down
  ema_alignment        TEXT,   -- bullish | partial_bullish | neutral | bearish
  vwap_state           TEXT,   -- above | reclaiming | below

  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT isnap_run_asset_tf_unique UNIQUE (scan_run_id, asset_id, timeframe),

  CONSTRAINT isnap_timeframe_check CHECK (
    timeframe IN ('4h', '1h', '30m')
  ),
  CONSTRAINT isnap_trend_state_check CHECK (
    trend_state IS NULL OR trend_state IN ('strong_up', 'up', 'neutral', 'down', 'strong_down')
  ),
  CONSTRAINT isnap_ema_alignment_check CHECK (
    ema_alignment IS NULL OR ema_alignment IN ('bullish', 'partial_bullish', 'neutral', 'bearish')
  ),
  CONSTRAINT isnap_vwap_state_check CHECK (
    vwap_state IS NULL OR vwap_state IN ('above', 'reclaiming', 'below')
  ),
  CONSTRAINT isnap_rsi_range_check CHECK (
    rsi_14 IS NULL OR (rsi_14 >= 0 AND rsi_14 <= 100)
  )
);

-- Indexes
CREATE INDEX idx_isnap_scan_run    ON indicator_snapshots (scan_run_id);
CREATE INDEX idx_isnap_asset       ON indicator_snapshots (asset_id);
CREATE INDEX idx_isnap_run_tf      ON indicator_snapshots (scan_run_id, timeframe);  -- fetch all 4H for a run

-- Comments
COMMENT ON TABLE  indicator_snapshots IS 'Per-asset per-scan per-timeframe indicator values. 3 rows/asset/run. 90-day retention.';
COMMENT ON COLUMN indicator_snapshots.timeframe         IS '4h = structure; 1h = momentum; 30m = entry timing.';
COMMENT ON COLUMN indicator_snapshots.snapshot_time     IS 'Timestamp of the most recent fully closed candle in this timeframe.';
COMMENT ON COLUMN indicator_snapshots.price_vs_ema20_pct IS 'Positive = above EMA20. >12% for clean = anti-chase rejection.';
COMMENT ON COLUMN indicator_snapshots.vwap_state        IS 'above: price > VWAP by >0.5%; reclaiming: crossed in last 3 candles; below: all other.';
COMMENT ON COLUMN indicator_snapshots.trend_state       IS 'Derived from EMA200 slope + price position vs EMA20/50/200.';
COMMENT ON COLUMN indicator_snapshots.ema_alignment     IS 'bullish = price > EMA20 > EMA50 > EMA200.';
