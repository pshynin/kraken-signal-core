-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0003: scan_runs
-- One row per scanner execution. Central FK anchor for all per-run tables.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE scan_runs (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at            TIMESTAMPTZ NOT NULL,
  completed_at          TIMESTAMPTZ,                   -- NULL while status = 'running'
  status                TEXT        NOT NULL DEFAULT 'running',
  triggered_by          TEXT        NOT NULL DEFAULT 'schedule',
  assets_scanned        INTEGER,                       -- total universe size
  assets_passed_filter  INTEGER,                       -- survived hard filter
  candidates_clean      INTEGER,                       -- final clean table count
  candidates_ugly       INTEGER,                       -- final ugly table count
  alerts_sent           INTEGER,                       -- Discord messages delivered
  scanner_version       TEXT,                          -- git SHA at run time
  error_message         TEXT,                          -- top-level error if status = 'failed'
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT scan_runs_status_check CHECK (
    status IN ('running', 'completed', 'failed', 'partial')
  ),
  CONSTRAINT scan_runs_triggered_by_check CHECK (
    triggered_by IN ('schedule', 'manual')
  )
);

-- Indexes
CREATE INDEX idx_scan_runs_started_at    ON scan_runs (started_at DESC);
CREATE INDEX idx_scan_runs_completed_at  ON scan_runs (completed_at DESC);
CREATE INDEX idx_scan_runs_status        ON scan_runs (status);

-- Comments
COMMENT ON TABLE  scan_runs IS 'One row per scanner execution. Used for run history, health checks, and per-run FK anchor.';
COMMENT ON COLUMN scan_runs.status          IS 'running → completed | failed | partial.';
COMMENT ON COLUMN scan_runs.triggered_by    IS 'schedule = GitHub Actions cron; manual = workflow_dispatch.';
COMMENT ON COLUMN scan_runs.scanner_version IS 'Git SHA of the scanner image/code used. Enables reproducibility audits.';
COMMENT ON COLUMN scan_runs.assets_passed_filter IS 'Assets remaining after hard exclusion rules.';
