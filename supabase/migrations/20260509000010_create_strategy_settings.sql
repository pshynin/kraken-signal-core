-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0010: strategy_settings
-- Runtime-configurable scanner thresholds and parameters.
-- Edit via the /settings dashboard page without code changes.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE strategy_settings (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  setting_key   TEXT        NOT NULL,    -- dotted path, e.g. 'clean.min_score'
  setting_value JSONB       NOT NULL,    -- typed JSON value (number, bool, string, object)
  description   TEXT,                   -- human-readable label shown in /settings UI
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT strategy_settings_key_unique UNIQUE (setting_key)
);

-- Indexes
CREATE INDEX idx_settings_key ON strategy_settings (setting_key);

-- Auto-stamp updated_at
CREATE TRIGGER strategy_settings_set_updated_at
  BEFORE UPDATE ON strategy_settings
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- Comments
COMMENT ON TABLE  strategy_settings IS 'Runtime-configurable scanner parameters. Seeded with defaults in migration 0012.';
COMMENT ON COLUMN strategy_settings.setting_key   IS 'Dotted key path, e.g. clean.min_score, scanner.alert_dedup_hours.';
COMMENT ON COLUMN strategy_settings.setting_value IS 'JSON-typed value. Scalar (number/bool/string) or nested object.';
COMMENT ON COLUMN strategy_settings.description   IS 'Human-readable label shown in the /settings UI.';
