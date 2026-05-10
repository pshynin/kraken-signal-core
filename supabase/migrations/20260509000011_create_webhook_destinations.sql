-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0011: webhook_destinations
-- Metadata for alert channel configuration.
-- IMPORTANT: Actual webhook URLs are stored in environment variables only.
--            This table records names, types, and which alert_types each receives.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE webhook_destinations (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT        NOT NULL,               -- e.g. 'discord-clean'
  channel_type  TEXT        NOT NULL DEFAULT 'discord',
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  alert_types   TEXT[]      NOT NULL,               -- which alert_type values this destination receives
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT webhook_destinations_name_unique UNIQUE (name),
  CONSTRAINT webhook_destinations_channel_type_check CHECK (
    channel_type IN ('discord')  -- extend when other platforms are added
  )
);

-- Indexes
CREATE INDEX idx_webhooks_is_active ON webhook_destinations (is_active);

-- Auto-stamp updated_at
CREATE TRIGGER webhook_destinations_set_updated_at
  BEFORE UPDATE ON webhook_destinations
  FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- Comments
COMMENT ON TABLE  webhook_destinations IS 'Alert channel metadata. Webhook URLs live in env vars, never in this table.';
COMMENT ON COLUMN webhook_destinations.name         IS 'Unique channel name that maps to a DISCORD_WEBHOOK_{NAME} env var.';
COMMENT ON COLUMN webhook_destinations.alert_types  IS 'Array of alert_type values this destination should receive.';
COMMENT ON COLUMN webhook_destinations.is_active    IS 'FALSE = destination is configured but temporarily suppressed.';
