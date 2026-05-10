-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0001: Shared utility functions
-- Must run first — subsequent migrations reference trigger_set_updated_at().
-- ─────────────────────────────────────────────────────────────────────────────

-- Reusable trigger function: stamp updated_at on every row UPDATE.
-- Referenced by: assets, candidate_recommendations, strategy_settings,
--                webhook_destinations
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION trigger_set_updated_at() IS
  'Automatically stamps updated_at = NOW() on every UPDATE. '
  'Attach as a BEFORE UPDATE trigger on any table with an updated_at column.';
