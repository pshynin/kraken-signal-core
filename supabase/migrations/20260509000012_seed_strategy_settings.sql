-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0012: seed strategy_settings + webhook_destinations
-- Default thresholds exactly matching the architecture specification.
-- All values are editable at runtime via the /settings dashboard.
-- ON CONFLICT DO NOTHING = safe to re-run (idempotent).
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Strategy settings ─────────────────────────────────────────────────────────
INSERT INTO strategy_settings (setting_key, setting_value, description) VALUES

  -- ── Global hard-exclusion thresholds ────────────────────────────────────────
  ('global.rsi_hard_min',
   '42',
   'RSI below this threshold → hard exclude asset regardless of category'),

  ('global.rsi_hard_max',
   '78',
   'RSI above this threshold → exclude or apply heavy score penalty'),

  -- ── Clean candidate thresholds ──────────────────────────────────────────────
  ('clean.min_score',
   '70',
   'Minimum total score (0–100) required for clean category'),

  ('clean.min_volume_7d_avg_usd',
   '5000000',
   '7-day average dollar volume floor for clean candidates ($5M)'),

  ('clean.min_volume_24h_usd',
   '2000000',
   '24-hour dollar volume floor for clean candidates ($2M)'),

  ('clean.min_atr_pct',
   '2.5',
   'ATR 7d minimum as % of price — below this = not enough movement'),

  ('clean.max_atr_pct',
   '18.0',
   'ATR 7d maximum as % of price — above this = execution becomes unreliable'),

  ('clean.max_return_3d',
   '0.30',
   'Max 3-day return before anti-chase rejection fires (+30%)'),

  ('clean.max_price_vs_ema20_pct',
   '12.0',
   'Max % price can be above EMA20 before anti-chase rejection (12%)'),

  ('clean.min_volume_ratio',
   '1.2',
   'Min volume ratio vs 20-day average — must show volume expansion'),

  ('clean.require_positive_rs_btc',
   'true',
   'Require positive 7-day relative strength vs BTC'),

  ('clean.max_entry_distance_pct',
   '5.0',
   'Entry zone must be within this % of current price to be actionable'),

  ('clean.min_reward_risk',
   '2.0',
   'Minimum reward/risk ratio for clean candidates'),

  ('clean.rsi_preferred_min',
   '52',
   'Preferred RSI lower bound for clean category'),

  ('clean.rsi_preferred_max',
   '68',
   'Preferred RSI upper bound for clean category'),

  -- ── Ugly pre-spike candidate thresholds ─────────────────────────────────────
  ('ugly.min_score',
   '62',
   'Minimum total score (0–100) required for ugly category'),

  ('ugly.min_volume_7d_avg_usd',
   '750000',
   '7-day average dollar volume floor for ugly candidates ($750k — adjustable)'),

  ('ugly.min_volume_24h_usd',
   '300000',
   '24-hour dollar volume floor for ugly candidates ($300k)'),

  ('ugly.min_atr_pct',
   '6.0',
   'ATR 7d minimum as % of price for ugly candidates'),

  ('ugly.max_atr_pct',
   '30.0',
   'ATR 7d maximum as % of price for ugly candidates'),

  ('ugly.max_return_3d',
   '0.40',
   'Max 3-day return before anti-chase rejection fires for ugly (+40%)'),

  ('ugly.max_price_vs_ema20_pct',
   '20.0',
   'Max % price can be above EMA20 before anti-chase rejection (20%)'),

  ('ugly.min_volume_ratio',
   '1.3',
   'Min volume ratio vs 20-day average for ugly candidates'),

  ('ugly.min_stop_pct',
   '8.0',
   'Minimum stop distance % from entry for ugly candidates'),

  ('ugly.max_stop_pct',
   '15.0',
   'Maximum stop distance % from entry for ugly candidates'),

  ('ugly.min_reward_risk',
   '2.5',
   'Minimum reward/risk ratio for ugly candidates'),

  ('ugly.rsi_preferred_min',
   '50',
   'Preferred RSI lower bound for ugly category'),

  ('ugly.rsi_preferred_max',
   '72',
   'Preferred RSI upper bound for ugly category'),

  -- ── Scanner behavior ─────────────────────────────────────────────────────────
  ('scanner.max_clean_candidates',
   '10',
   'Maximum number of candidates to include in the clean output table'),

  ('scanner.max_ugly_candidates',
   '10',
   'Maximum number of candidates to include in the ugly output table'),

  ('scanner.min_score_delta_for_rotation',
   '3.0',
   'New candidate must outscore an existing top-N candidate by at least this much to rotate it out (stability rule)'),

  ('scanner.alert_dedup_hours',
   '8',
   'Recency window (hours) for New vs Updated alerts: a coin alerted within this window shows as Updated (with a price delta since its last alert); otherwise New. Does not suppress alerts.'),

  ('scanner.stale_run_threshold_hours',
   '6',
   'Hours since last successful run before a system alert fires'),

  ('scanner.min_trade_size_usd',
   '2000',
   'Minimum practical trade size ($). Exclude assets that cannot support this with acceptable slippage.'),

  -- ── Probability mapping (score thresholds → heuristic percentiles) ───────────
  ('scoring.probability_map',
   '{"85": 90.0, "78": 84.0, "70": 77.0, "62": 69.0}',
   'Maps minimum score thresholds to heuristic success probability percentiles. Keys are score floor, values are percentile.'),

  -- ── Size bucket assignment thresholds ────────────────────────────────────────
  ('sizing.clean_20k_plus',
   '{"min_score": 82, "min_volume_7d_avg_usd": 50000000}',
   'Conditions required to assign 20k+ size bucket (clean candidates only)'),

  ('sizing.clean_10k_20k',
   '{"min_score": 75, "min_volume_7d_avg_usd": 20000000}',
   'Conditions required to assign 10k–20k size bucket (clean candidates only)'),

  ('sizing.clean_5k_10k',
   '{"min_score": 70, "min_volume_7d_avg_usd": 10000000}',
   'Conditions required to assign 5k–10k size bucket (clean candidates only)'),

  ('sizing.ugly_5k_10k',
   '{"min_score": 70, "min_volume_7d_avg_usd": 5000000}',
   'Conditions required to assign 5k–10k size bucket (ugly candidates)'),

  ('sizing.ugly_2k_5k',
   '{"min_score": 65}',
   'Conditions required to assign 2k–5k size bucket (ugly candidates). Default ugly bucket.')

ON CONFLICT (setting_key) DO NOTHING;


-- ── Webhook destinations ──────────────────────────────────────────────────────
-- Metadata only — actual URLs are in DISCORD_WEBHOOK_* environment variables.
INSERT INTO webhook_destinations (name, channel_type, is_active, alert_types) VALUES
  ('discord-clean',
   'discord',
   TRUE,
   ARRAY['new_candidate', 'state_change', 'invalidation']),

  ('discord-ugly',
   'discord',
   TRUE,
   ARRAY['new_candidate', 'state_change', 'invalidation']),

  ('discord-system',
   'discord',
   TRUE,
   ARRAY['system'])

ON CONFLICT (name) DO NOTHING;
