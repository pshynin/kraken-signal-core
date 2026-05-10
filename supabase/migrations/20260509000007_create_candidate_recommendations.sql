-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0007: candidate_recommendations
-- Final ranked output — the actual trade tables.
-- One row per (scan_run, asset) that survived scoring and threshold filters.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE candidate_recommendations (
  id                    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id           UUID          NOT NULL REFERENCES scan_runs(id)       ON DELETE CASCADE,
  asset_id              UUID          NOT NULL REFERENCES assets(id)           ON DELETE RESTRICT,
  score_id              UUID          NOT NULL REFERENCES candidate_scores(id) ON DELETE RESTRICT,

  -- ── Classification & ranking ────────────────────────────────────────────────
  category              TEXT          NOT NULL,      -- 'clean' | 'ugly'
  rank                  INTEGER       NOT NULL,      -- 1 = best in category

  -- ── Trade parameters (all in USD) ──────────────────────────────────────────
  entry_price           NUMERIC(20,8) NOT NULL,      -- midpoint of entry zone
  entry_price_low       NUMERIC(20,8),               -- lower bound of entry zone
  entry_price_high      NUMERIC(20,8),               -- upper bound of entry zone
  exit_price            NUMERIC(20,8) NOT NULL,      -- target / sell order price
  stop_loss             NUMERIC(20,8) NOT NULL,      -- stop loss price

  -- ── Sizing ──────────────────────────────────────────────────────────────────
  suggested_size_bucket TEXT          NOT NULL,      -- '2k' | '2k-5k' | '5k-10k' | '10k-20k' | '20k+'

  -- ── Performance estimates ───────────────────────────────────────────────────
  probability_pct       NUMERIC(5,2),               -- copied from candidate_scores for convenience
  expected_gain_pct     NUMERIC(8,4),               -- (exit - entry_midpoint) / entry_midpoint × 100
  reward_risk_ratio     NUMERIC(6,3),               -- (exit - entry) / (entry - stop_loss)

  -- ── Human-readable rationale ────────────────────────────────────────────────
  notes                 TEXT,

  -- ── Lifecycle state machine ─────────────────────────────────────────────────
  state                 TEXT          NOT NULL DEFAULT 'candidate_clean',

  created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

  CONSTRAINT crecs_run_asset_unique UNIQUE (scan_run_id, asset_id),

  CONSTRAINT crecs_category_check CHECK (
    category IN ('clean', 'ugly')
  ),
  CONSTRAINT crecs_size_bucket_check CHECK (
    suggested_size_bucket IN ('2k', '2k-5k', '5k-10k', '10k-20k', '20k+')
  ),
  CONSTRAINT crecs_state_check CHECK (
    state IN (
      'excluded', 'candidate_clean', 'candidate_ugly',
      'alerted', 'active', 'invalidated', 'expired',
      'entered', 'target_hit', 'stop_hit', 'manually_closed'
    )
  ),
  CONSTRAINT crecs_rank_positive CHECK (rank > 0),
  CONSTRAINT crecs_rr_positive CHECK (
    reward_risk_ratio IS NULL OR reward_risk_ratio > 0
  ),
  CONSTRAINT crecs_entry_zone_order CHECK (
    entry_price_low IS NULL OR entry_price_high IS NULL
    OR entry_price_low <= entry_price_high
  ),
  CONSTRAINT crecs_stop_below_entry CHECK (
    stop_loss < entry_price
  ),
  CONSTRAINT crecs_exit_above_entry CHECK (
    exit_price > entry_price
  )
);

-- Indexes
CREATE INDEX idx_crecs_scan_run     ON candidate_recommendations (scan_run_id);
CREATE INDEX idx_crecs_category     ON candidate_recommendations (scan_run_id, category, rank);
CREATE INDEX idx_crecs_state        ON candidate_recommendations (state);
CREATE INDEX idx_crecs_asset        ON candidate_recommendations (asset_id);

-- Auto-stamp updated_at
CREATE TRIGGER crecs_set_updated_at
  BEFORE UPDATE ON candidate_recommendations
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- Comments
COMMENT ON TABLE  candidate_recommendations IS 'Final ranked trade output. One row per (scan_run, asset) that passed all filters.';
COMMENT ON COLUMN candidate_recommendations.entry_price       IS 'Computed entry midpoint. Use entry_price_low–high for the order range.';
COMMENT ON COLUMN candidate_recommendations.expected_gain_pct IS 'Realistic 7–10 day upside from entry midpoint to exit. Not maximum theoretical.';
COMMENT ON COLUMN candidate_recommendations.state             IS 'Lifecycle state: candidate_* → alerted → active → invalidated | expired | target_hit | stop_hit.';
COMMENT ON COLUMN candidate_recommendations.notes             IS 'Scanner-generated rationale string. Shown in Discord embed and dashboard.';
