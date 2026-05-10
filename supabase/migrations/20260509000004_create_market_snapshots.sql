-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0004: market_snapshots
-- Per-asset per-scan computed market metrics. One row per (scan_run, asset).
-- Retention guidance: 90 days (add pg_cron cleanup in a future migration).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE market_snapshots (
  id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id         UUID          NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  asset_id            UUID          NOT NULL REFERENCES assets(id)    ON DELETE RESTRICT,
  snapshot_time       TIMESTAMPTZ   NOT NULL,

  -- ── Price ──────────────────────────────────────────────────────────────────
  price_usd           NUMERIC(20,8) NOT NULL,
  price_btc           NUMERIC(20,10),           -- price expressed in BTC (for relative strength)

  -- ── Volume ─────────────────────────────────────────────────────────────────
  volume_24h_usd      NUMERIC(20,2),            -- rolling 24h dollar volume
  volume_7d_avg_usd   NUMERIC(20,2),            -- 7-day average daily dollar volume
  volume_ratio_20d    NUMERIC(8,4),             -- volume_24h / 20-day average daily volume

  -- ── Returns (fractional, e.g. 0.08 = +8%) ─────────────────────────────────
  return_3d           NUMERIC(8,4),
  return_7d           NUMERIC(8,4),
  return_14d          NUMERIC(8,4),
  return_vs_btc_7d    NUMERIC(8,4),             -- 7d return minus BTC 7d return

  -- ── Distance metrics (fractional; negative = below reference) ──────────────
  dist_from_7d_high   NUMERIC(8,4),             -- e.g. -0.05 = 5% below 7d high
  dist_from_20d_high  NUMERIC(8,4),

  -- ── Execution quality ──────────────────────────────────────────────────────
  spread_pct          NUMERIC(8,6),             -- estimated bid-ask spread as % of mid
  atr_pct_7d          NUMERIC(8,4),             -- ATR 14 on 4H, expressed as % of price

  created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

  CONSTRAINT market_snapshots_run_asset_unique UNIQUE (scan_run_id, asset_id)
);

-- Indexes
CREATE INDEX idx_msnap_scan_run       ON market_snapshots (scan_run_id);
CREATE INDEX idx_msnap_asset          ON market_snapshots (asset_id);
CREATE INDEX idx_msnap_snapshot_time  ON market_snapshots (snapshot_time DESC);

-- Comments
COMMENT ON TABLE  market_snapshots IS 'Per-asset per-scan market metrics. One row per (scan_run, asset). 90-day retention.';
COMMENT ON COLUMN market_snapshots.volume_ratio_20d   IS 'volume_24h_usd / 20-day average. >1.2 = volume expansion.';
COMMENT ON COLUMN market_snapshots.return_vs_btc_7d   IS 'Relative strength proxy: positive = outperforming BTC over 7 days.';
COMMENT ON COLUMN market_snapshots.dist_from_7d_high  IS 'Negative = below 7d high. -0.05 = 5% below. Used for anti-chase.';
COMMENT ON COLUMN market_snapshots.spread_pct         IS 'Estimated bid-ask spread from L2 or OHLC proxy. Used for liquidity scoring.';
COMMENT ON COLUMN market_snapshots.atr_pct_7d         IS 'ATR 14 on 4H candles expressed as % of current price.';
