-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0002: assets
-- Tracks the full Kraken spot universe. Updated each scan run.
-- ─────────────────────────────────────────────────────────────────────────────

-- RLS note: disabled for single-user MVP.
-- Enable + add policies when multi-user support is required.

CREATE TABLE assets (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol          TEXT        NOT NULL,         -- e.g. BTC, SOL, AVAX
  kraken_pair     TEXT        NOT NULL,         -- e.g. XXBTZUSD, SOLUSDT
  base_currency   TEXT        NOT NULL,         -- e.g. BTC
  quote_currency  TEXT        NOT NULL DEFAULT 'USD',
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,  -- Kraken still lists it
  excluded_reason TEXT,                         -- NULL = not excluded; set = permanent exclusion reason
  first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- updated each scan run
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT assets_symbol_unique     UNIQUE (symbol),
  CONSTRAINT assets_kraken_pair_unique UNIQUE (kraken_pair)
);

-- Indexes
CREATE INDEX idx_assets_is_active  ON assets (is_active);
CREATE INDEX idx_assets_last_seen  ON assets (last_seen_at DESC);

-- Auto-stamp updated_at
CREATE TRIGGER assets_set_updated_at
  BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- Comments
COMMENT ON TABLE  assets IS 'Kraken spot universe — one row per tradable asset. Updated each scan run.';
COMMENT ON COLUMN assets.symbol          IS 'Short ticker, e.g. BTC. Unique across all assets.';
COMMENT ON COLUMN assets.kraken_pair     IS 'Kraken API pair name, e.g. XXBTZUSD. Unique.';
COMMENT ON COLUMN assets.is_active       IS 'FALSE when Kraken delists the pair.';
COMMENT ON COLUMN assets.excluded_reason IS 'Non-NULL = permanently excluded; scanner skips this asset.';
