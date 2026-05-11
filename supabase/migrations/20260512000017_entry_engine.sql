-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0017: entry engine — setup_type + preferred/max entry columns
--
-- Adds the columns required by the three-setup deterministic entry engine:
--   setup_type           — pullback | breakout_trigger | reclaim
--   preferred_entry      — ideal limit order price (replaces entry_price semantically)
--   max_entry            — chase ceiling (replaces entry_price_high semantically)
--   support_anchor_type  — which indicator level was used as anchor
--   support_anchor_value — raw anchor price
--
-- entry_price, entry_price_low, entry_price_high are retained for backward
-- compatibility; their values equal preferred_entry, preferred*0.995, max_entry.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE candidate_recommendations
  ADD COLUMN setup_type           TEXT,
  ADD COLUMN preferred_entry      NUMERIC(20, 8),
  ADD COLUMN max_entry            NUMERIC(20, 8),
  ADD COLUMN support_anchor_type  TEXT,
  ADD COLUMN support_anchor_value NUMERIC(20, 8);

COMMENT ON COLUMN candidate_recommendations.setup_type IS
  'Setup classification: pullback | breakout_trigger | reclaim';

COMMENT ON COLUMN candidate_recommendations.preferred_entry IS
  'Optimal limit order price. Place the buy order here. Always < market_price_at_scan except for breakout_trigger.';

COMMENT ON COLUMN candidate_recommendations.max_entry IS
  'Chase ceiling. Do not buy above this price. Replaces entry_price_high semantics.';

COMMENT ON COLUMN candidate_recommendations.support_anchor_type IS
  'Indicator level used to anchor the entry: ema_20 | ema_50 | vwap | atr_fallback | 20d_high_trigger | above_20d_high';

COMMENT ON COLUMN candidate_recommendations.support_anchor_value IS
  'Raw price of the support/trigger anchor at scan time.';

CREATE INDEX idx_crecs_setup_type ON candidate_recommendations (setup_type);
