-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0006: candidate_scores
-- 9-factor scoring breakdown for every asset in every scan.
-- Includes excluded assets (with exclusion_reason). Retained forever for audit.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE candidate_scores (
  id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id        UUID        NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  asset_id           UUID        NOT NULL REFERENCES assets(id)    ON DELETE RESTRICT,

  -- ── Classification ──────────────────────────────────────────────────────────
  category           TEXT,                     -- clean | ugly | excluded | watchlist
  exclusion_reason   TEXT,                     -- first failing hard filter rule; NULL if not excluded

  -- ── Score breakdown (weights sum to 100) ───────────────────────────────────
  score_total        NUMERIC(5,2),             -- 0–100
  score_liquidity    NUMERIC(5,2),             -- /20 — liquidity & tradability
  score_upside       NUMERIC(5,2),             -- /15 — 7–10 day upside feasibility
  score_volatility   NUMERIC(5,2),             -- /10 — volatility expansion
  score_structure    NUMERIC(5,2),             -- /15 — structure quality
  score_rel_strength NUMERIC(5,2),             -- /10 — relative strength vs BTC
  score_volume       NUMERIC(5,2),             -- /10 — volume confirmation
  score_catalyst     NUMERIC(5,2),             -- /10 — catalyst / attention
  score_supply_risk  NUMERIC(5,2),             -- /5  — supply / token risk
  score_execution    NUMERIC(5,2),             -- /5  — execution clarity

  -- ── Derived ─────────────────────────────────────────────────────────────────
  probability_pct    NUMERIC(5,2),             -- heuristic percentile mapped from score_total
  rank_in_category   INTEGER,                  -- NULL for excluded; 1 = best in category

  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT cscores_run_asset_unique UNIQUE (scan_run_id, asset_id),

  CONSTRAINT cscores_category_check CHECK (
    category IS NULL OR category IN ('clean', 'ugly', 'excluded', 'watchlist')
  ),
  CONSTRAINT cscores_total_range CHECK (
    score_total IS NULL OR (score_total >= 0 AND score_total <= 100)
  ),
  CONSTRAINT cscores_rank_positive CHECK (
    rank_in_category IS NULL OR rank_in_category > 0
  )
);

-- Indexes
CREATE INDEX idx_cscores_scan_run  ON candidate_scores (scan_run_id);
CREATE INDEX idx_cscores_category  ON candidate_scores (scan_run_id, category);
CREATE INDEX idx_cscores_total     ON candidate_scores (scan_run_id, score_total DESC NULLS LAST);

-- Comments
COMMENT ON TABLE  candidate_scores IS '9-factor score breakdown per asset per scan. Includes excluded assets with reason.';
COMMENT ON COLUMN candidate_scores.score_liquidity   IS '/20. Liquidity and tradability. Primary gate.';
COMMENT ON COLUMN candidate_scores.score_upside      IS '/15. 7–10 day upside feasibility given structure.';
COMMENT ON COLUMN candidate_scores.score_volatility  IS '/10. Volatility expansion / compression detection.';
COMMENT ON COLUMN candidate_scores.score_structure   IS '/15. Multi-timeframe structure quality.';
COMMENT ON COLUMN candidate_scores.score_rel_strength IS '/10. Relative strength vs BTC over 7 days.';
COMMENT ON COLUMN candidate_scores.score_volume      IS '/10. Volume confirmation of move.';
COMMENT ON COLUMN candidate_scores.score_catalyst    IS '/10. Catalyst / market attention proxy.';
COMMENT ON COLUMN candidate_scores.score_supply_risk IS '/5.  Supply overhang / token unlock risk.';
COMMENT ON COLUMN candidate_scores.score_execution   IS '/5.  Entry/exit execution clarity.';
COMMENT ON COLUMN candidate_scores.probability_pct   IS 'Heuristic success percentile. Not a guarantee. Mapped: 85→90%, 78→84%, 70→77%, 62→69%.';
COMMENT ON COLUMN candidate_scores.exclusion_reason  IS 'First failing hard-filter rule. Human-readable string.';
