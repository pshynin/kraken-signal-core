-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0008: alerts_sent
-- Deduplication log and delivery history for all Discord alerts.
-- The dedup query pattern:
--   SELECT 1 FROM alerts_sent
--   WHERE asset_id = $1 AND alert_type = 'new_candidate'
--     AND delivery_status = 'sent'
--     AND sent_at > NOW() - INTERVAL '8 hours'
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE alerts_sent (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id       UUID        NOT NULL REFERENCES scan_runs(id)               ON DELETE RESTRICT,
  recommendation_id UUID        REFERENCES candidate_recommendations(id)         ON DELETE SET NULL,
  asset_id          UUID        NOT NULL REFERENCES assets(id)                  ON DELETE RESTRICT,

  -- ── Alert metadata ──────────────────────────────────────────────────────────
  alert_type        TEXT        NOT NULL,   -- new_candidate | state_change | expiry_warning | invalidation | system
  channel           TEXT        NOT NULL,   -- discord_clean | discord_ugly | discord_system

  -- ── Webhook tracking (URL never stored; SHA-256 hash only) ─────────────────
  webhook_url_hash  TEXT        NOT NULL,   -- SHA-256 hex digest of the webhook URL

  -- ── Payload ─────────────────────────────────────────────────────────────────
  payload           JSONB       NOT NULL,   -- full Discord embed payload that was sent

  -- ── Delivery ────────────────────────────────────────────────────────────────
  delivery_status   TEXT        NOT NULL DEFAULT 'pending',  -- pending | sent | failed
  sent_at           TIMESTAMPTZ,           -- NULL until delivery_status = 'sent'
  error_message     TEXT,                  -- HTTP error or exception message on failure

  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT alerts_sent_alert_type_check CHECK (
    alert_type IN ('new_candidate', 'state_change', 'expiry_warning', 'invalidation', 'system')
  ),
  CONSTRAINT alerts_sent_channel_check CHECK (
    channel IN ('discord_clean', 'discord_ugly', 'discord_system')
  ),
  CONSTRAINT alerts_sent_delivery_status_check CHECK (
    delivery_status IN ('pending', 'sent', 'failed')
  )
);

-- Indexes
-- Primary dedup lookup: asset + alert_type + recency
CREATE INDEX idx_alerts_asset_type_sent ON alerts_sent (asset_id, alert_type, sent_at DESC);
CREATE INDEX idx_alerts_scan_run        ON alerts_sent (scan_run_id);
CREATE INDEX idx_alerts_delivery_status ON alerts_sent (delivery_status);
CREATE INDEX idx_alerts_sent_at         ON alerts_sent (sent_at DESC);

-- Comments
COMMENT ON TABLE  alerts_sent IS 'Delivery log and dedup gate for all Discord alerts. Retain 90 days.';
COMMENT ON COLUMN alerts_sent.webhook_url_hash  IS 'SHA-256 hex of the webhook URL. Actual URL lives in env vars only.';
COMMENT ON COLUMN alerts_sent.recommendation_id IS 'NULL for system alerts or if recommendation was later pruned.';
COMMENT ON COLUMN alerts_sent.payload           IS 'Exact Discord embed payload. Enables retry and audit.';
