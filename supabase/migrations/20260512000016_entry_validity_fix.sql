-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0016: entry validity fix
--
-- Adds market_price_at_scan to candidate_recommendations.
-- Records the spot price at scan time so the dashboard can display
-- how far below market the pullback entry is, and audit that
-- entry_price < market_price_at_scan (pullback-first invariant).
--
-- Nullable — existing rows have no scan-time price recorded.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE candidate_recommendations
  ADD COLUMN market_price_at_scan NUMERIC(20, 8);

COMMENT ON COLUMN candidate_recommendations.market_price_at_scan IS
  'Spot price (USD) at scan time. entry_price must be < this value for valid pullback-first long entries.';
