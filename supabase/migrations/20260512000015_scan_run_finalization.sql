-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0015: scan_run finalization + timed_out status
--
-- 1. Adds 'timed_out' to scan_runs.status allowed values.
--    Rows in 'running' state that never received a completed_at are
--    auto-marked 'timed_out' by the scanner at next startup.
--
-- 2. Adds 'ci' to scan_runs.triggered_by allowed values.
--    Allows GitHub Actions CI jobs to distinguish from scheduled runs.
--
-- 3. Seeds scanner.run_timeout_minutes into strategy_settings.
--    Controls the configurable threshold used by timeout_stale_scan_runs().
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Widen status check constraint
ALTER TABLE scan_runs DROP CONSTRAINT scan_runs_status_check;
ALTER TABLE scan_runs ADD CONSTRAINT scan_runs_status_check CHECK (
  status IN ('running', 'completed', 'failed', 'partial', 'timed_out')
);

-- 2. Widen triggered_by check constraint
ALTER TABLE scan_runs DROP CONSTRAINT scan_runs_triggered_by_check;
ALTER TABLE scan_runs ADD CONSTRAINT scan_runs_triggered_by_check CHECK (
  triggered_by IN ('schedule', 'manual', 'ci')
);

-- 3. Seed run_timeout_minutes setting
INSERT INTO strategy_settings (setting_key, setting_value, description) VALUES
  ('scanner.run_timeout_minutes',
   '120',
   'Minutes after which a scan_run stuck in running state (completed_at IS NULL) is auto-marked timed_out at next scanner startup')
ON CONFLICT (setting_key) DO NOTHING;
