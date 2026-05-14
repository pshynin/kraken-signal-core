-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: extend candidate_scores.cscores_category_check
--
-- The scoring engine now emits a distinct 'low_score' category for assets
-- that score below watchlist_min_score (default 55). Previously these rows
-- silently fell through to 'watchlist'; treating them as a separate category
-- keeps the audit trail honest and the watchlist floor meaningful.
--
-- 'excluded' remains reserved for hard-filter failures (scoring engine never
-- produces it directly — the persister sets it for FilterResult.exclusions).
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE candidate_scores DROP CONSTRAINT cscores_category_check;

ALTER TABLE candidate_scores ADD CONSTRAINT cscores_category_check CHECK (
  category IS NULL OR category IN ('clean', 'ugly', 'excluded', 'watchlist', 'low_score')
);
