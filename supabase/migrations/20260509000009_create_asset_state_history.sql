-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0009: asset_state_history
-- Immutable audit trail for the asset lifecycle state machine.
-- Records every state transition with context. Never updated or deleted.
-- Retained forever (small rows, high debugging value).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE asset_state_history (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id    UUID        NOT NULL REFERENCES assets(id)    ON DELETE RESTRICT,
  scan_run_id UUID        REFERENCES scan_runs(id)           ON DELETE SET NULL,  -- kept even if run pruned

  -- ── Transition ──────────────────────────────────────────────────────────────
  from_state  TEXT,                   -- NULL on first-ever transition for this asset
  to_state    TEXT        NOT NULL,   -- target state after this event

  -- ── Context ─────────────────────────────────────────────────────────────────
  reason      TEXT,                   -- human-readable: 'new_candidate' | 'hard_filter_fail' | etc.
  metadata    JSONB,                  -- score, price, volume, rank at time of transition

  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()  -- immutable; no updated_at
);

-- Indexes
CREATE INDEX idx_state_hist_asset    ON asset_state_history (asset_id, created_at DESC);
CREATE INDEX idx_state_hist_run      ON asset_state_history (scan_run_id);
CREATE INDEX idx_state_hist_to_state ON asset_state_history (to_state);

-- Comments
COMMENT ON TABLE  asset_state_history IS 'Immutable audit trail of asset state machine transitions. Never updated or deleted.';
COMMENT ON COLUMN asset_state_history.from_state  IS 'Previous state. NULL on very first transition.';
COMMENT ON COLUMN asset_state_history.to_state    IS 'New state after this event.';
COMMENT ON COLUMN asset_state_history.reason      IS 'Human-readable trigger: new_candidate, hard_filter_fail, score_drop, etc.';
COMMENT ON COLUMN asset_state_history.metadata    IS 'Snapshot of score, price, volume, rank at time of transition. JSON.';
COMMENT ON COLUMN asset_state_history.scan_run_id IS 'NULL if the triggering run was later pruned (SET NULL on DELETE).';
