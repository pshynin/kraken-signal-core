-- ─────────────────────────────────────────────────────────────────────────────
-- Migration: CHECK constraint on asset_state_history.to_state
--
-- to_state was previously unconstrained TEXT — the allowed value set was
-- enforced only by convention and by docs/state-machine.md. The scanner's
-- state vocabulary is now stable (PR 2 added entry_rejected + low_score;
-- those are the last additions for the final-state scope), so it is safe
-- to pin the set at the database level.
--
-- The 7 values below are exactly what scanner/state_machine.py writes:
--   candidate_clean / candidate_ugly  (record_initial_transitions, line 106)
--   excluded                          (record_initial_transitions, line 135)
--   watchlist                         (record_initial_transitions, line 151)
--   low_score                         (record_initial_transitions, line 170)
--   entry_rejected                    (record_initial_transitions, line 189)
--   alerted                           (record_alerted_transition,   line 276)
--
-- Plain ADD CONSTRAINT (not NOT VALID): Postgres validates existing rows
-- at migration time. If a legacy row holds an out-of-set value the
-- migration fails loudly — that is the intended signal for this
-- single-DB personal project, not something to paper over.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE asset_state_history ADD CONSTRAINT ash_to_state_check CHECK (
  to_state IN (
    'candidate_clean',
    'candidate_ugly',
    'watchlist',
    'low_score',
    'entry_rejected',
    'excluded',
    'alerted'
  )
);
