-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: extend candidate_recommendations size buckets from 5 to 8 tiers
--
-- The old 5-tier scheme ('2k' | '2k-5k' | '5k-10k' | '10k-20k' | '20k+') is
-- replaced by an 8-tier scheme with finer upper-end granularity:
--   2k | 2k-5k | 5k-10k | 10k-20k | 20k-35k | 35k-50k | 50k-100k | 100k+
--
-- Migration strategy: drop constraint, backfill existing rows, recreate
-- constraint with the new value set only. Leaves no rows holding values
-- outside the new constraint.
--
-- Backfill mapping (lossy for old '20k+' rows — see CHANGELOG for rationale):
--   '20k+' → '20k-35k'   (conservative; old "smallest 20k+" tier maps to
--                         new "smallest 20k+" tier)
--   all other old values are preserved unchanged.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE candidate_recommendations DROP CONSTRAINT crecs_size_bucket_check;

UPDATE candidate_recommendations
SET    suggested_size_bucket = '20k-35k'
WHERE  suggested_size_bucket = '20k+';

ALTER TABLE candidate_recommendations ADD CONSTRAINT crecs_size_bucket_check CHECK (
  suggested_size_bucket IN (
    '2k', '2k-5k', '5k-10k', '10k-20k',
    '20k-35k', '35k-50k', '50k-100k', '100k+'
  )
);
