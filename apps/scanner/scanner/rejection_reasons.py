"""Entry-engine rejection reason constants.

Shared between `entry_engine.py` (raise site) and `state_machine.py` (audit
writer). When the entry engine cannot produce a valid trade plan for a scored
candidate — e.g. the only viable anchor sits above market price, or a
breakout is too far past its trigger — the candidate is dropped from
`SelectionResult.clean`/`.ugly` and recorded in `asset_state_history` with
`to_state='entry_rejected'` and `reason` set to one of the constants below.

A candidate may be rejected for exactly one reason per scan run. Reasons are
recorded verbatim (no translation) so historical rows remain decodable when
constants are renamed or added.
"""

from __future__ import annotations

# Pullback setup: the chase ceiling (`max_entry`) is at or above current price,
# meaning the pullback is no longer reachable from below.
ENTRY_REJECT_PULLBACK_MAX_ABOVE_PRICE = "pullback_max_entry_above_price"

# Reclaim setup: the chase ceiling (`max_entry`) is at or above current price.
ENTRY_REJECT_RECLAIM_MAX_ABOVE_PRICE = "reclaim_max_entry_above_price"

# Breakout setup: preferred entry exceeds current price by more than the
# configured chase ceiling (`max_chase_current_price_pct`).
ENTRY_REJECT_BREAKOUT_CHASE_CEILING = "breakout_chase_ceiling_exceeded"

# Reclaim setup: no support level (EMA-20 / VWAP) within the proximity window
# below current price — no valid reclaim anchor exists.
ENTRY_REJECT_NO_QUALIFIED_ANCHOR = "no_qualified_anchor"

# Breakout setup: `dist_from_20d_high` was required to reconstruct the 20-day
# high but is absent from the asset's metrics.
ENTRY_REJECT_MISSING_DIST_20D = "missing_dist_from_20d_high"

# Catch-all for unexpected entry-engine failures. Logged with detail; this
# constant is only used when an exception's reason cannot be classified.
ENTRY_REJECT_UNKNOWN = "unknown_entry_error"

ENTRY_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        ENTRY_REJECT_PULLBACK_MAX_ABOVE_PRICE,
        ENTRY_REJECT_RECLAIM_MAX_ABOVE_PRICE,
        ENTRY_REJECT_BREAKOUT_CHASE_CEILING,
        ENTRY_REJECT_NO_QUALIFIED_ANCHOR,
        ENTRY_REJECT_MISSING_DIST_20D,
        ENTRY_REJECT_UNKNOWN,
    }
)
"""All valid `entry_rejected` reason strings. Use for test assertions and
input validation when reading historical rows back."""
