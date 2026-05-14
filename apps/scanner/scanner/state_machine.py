"""Asset State Machine — PR 11.

Writes the immutable asset_state_history audit trail. Called in two places:
    1. persist_run() via record_initial_transitions() — one row per processed
       asset covering: candidate_clean, candidate_ugly, watchlist, excluded.
    2. run_alerter() via record_alerted_transition() — one row per successful
       Discord delivery, transitioning candidate_* → alerted.

State values used by the scanner:
    candidate_clean   — selected clean candidate (recommendation written)
    candidate_ugly    — selected ugly candidate  (recommendation written)
    watchlist         — scored at or above watchlist_min_score but not selected
    low_score         — scored below watchlist_min_score (distinct from excluded)
    entry_rejected    — selected but dropped by the entry engine (no valid plan)
    excluded          — failed hard filter
    alerted           — Discord alert sent successfully

reason values stored in asset_state_history.reason:
    new_candidate            — first time in this category (from_state differs)
    retained_candidate       — same category as previous run
    watchlist_entry          — score >= watchlist_min_score, not selected
    low_score_entry          — score < watchlist_min_score
    <entry_rejection_reason> — one of scanner.rejection_reasons.*
    <exclusion_reason>       — copied from HardFilterResult.exclusion_reason
    alerted                  — written by record_alerted_transition

Public API:
    record_initial_transitions(
        client, scan_run_id, asset_id_map,
        filter_result, scoring_result, selection_result,
    ) -> int

    record_alerted_transition(
        client, scan_run_id, asset_id, from_state, metadata=None,
    ) -> None
"""

from __future__ import annotations

import logging
from typing import Any, cast

from supabase import Client

from scanner.models import FilterResult, ScoringResult, SelectionResult

log = logging.getLogger(__name__)

_BATCH_SIZE = 200


# ── Internal helpers ──────────────────────────────────────────────────────────


def _resolve_previous_states(
    client: Client,
    asset_ids: list[str],
) -> dict[str, str]:
    """Return {asset_id: most_recent_to_state} from asset_state_history.

    Batches the .in_() query into chunks of _BATCH_SIZE to avoid exceeding
    PostgREST URL length limits when querying 600+ asset UUIDs at once.
    Results are merged and deduplicated in the application layer (first
    occurrence per asset_id when ordered DESC = most recent entry).
    """
    if not asset_ids:
        return {}

    prev: dict[str, str] = {}

    for start in range(0, len(asset_ids), _BATCH_SIZE):
        chunk = asset_ids[start : start + _BATCH_SIZE]
        limit = max(len(chunk) * 3, 100)
        resp = (
            client.table("asset_state_history")
            .select("asset_id, to_state")
            .in_("asset_id", chunk)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        for row in cast(list[dict[str, Any]], resp.data or []):
            aid = str(row["asset_id"])
            if aid not in prev:
                prev[aid] = str(row["to_state"])

    return prev


def _build_transition_rows(
    scan_run_id: str,
    asset_id_map: dict[str, str],
    prev_states: dict[str, str],
    filter_result: FilterResult,
    scoring_result: ScoringResult,
    selection_result: SelectionResult,
) -> list[dict[str, Any]]:
    """Build asset_state_history insert rows for all processed assets."""
    rows: list[dict[str, Any]] = []

    # ── Selected candidates ────────────────────────────────────────────────────
    for candidate in selection_result.all_candidates:
        asset_id = asset_id_map.get(candidate.symbol)
        if not asset_id:
            continue
        to_state = f"candidate_{candidate.category}"  # candidate_clean | candidate_ugly
        from_state = prev_states.get(asset_id)
        reason = "retained_candidate" if from_state == to_state else "new_candidate"
        rows.append(
            {
                "asset_id": asset_id,
                "scan_run_id": scan_run_id,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
                "metadata": {
                    "score_total": candidate.score.score_total,
                    "rank": candidate.rank,
                    "probability_pct": candidate.score.probability_pct,
                    "price_usd": candidate.market.price_usd,
                },
            }
        )

    # ── Hard-filtered (excluded) assets ───────────────────────────────────────
    for hfr in filter_result.exclusions:
        asset_id = asset_id_map.get(hfr.symbol)
        if not asset_id:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "scan_run_id": scan_run_id,
                "from_state": prev_states.get(asset_id),
                "to_state": "excluded",
                "reason": hfr.exclusion_reason,
                "metadata": None,
            }
        )

    # ── Watchlist (scored at or above watchlist_min_score, not selected) ──────
    for score_bd in scoring_result.watchlist:
        asset_id = asset_id_map.get(score_bd.symbol)
        if not asset_id:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "scan_run_id": scan_run_id,
                "from_state": prev_states.get(asset_id),
                "to_state": "watchlist",
                "reason": "watchlist_entry",
                "metadata": {
                    "score_total": score_bd.score_total,
                    "probability_pct": score_bd.probability_pct,
                },
            }
        )

    # ── Low-score (scored below watchlist_min_score) ──────────────────────────
    for score_bd in scoring_result.low_score:
        asset_id = asset_id_map.get(score_bd.symbol)
        if not asset_id:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "scan_run_id": scan_run_id,
                "from_state": prev_states.get(asset_id),
                "to_state": "low_score",
                "reason": "low_score_entry",
                "metadata": {
                    "score_total": score_bd.score_total,
                    "probability_pct": score_bd.probability_pct,
                },
            }
        )

    # ── Entry-rejected (selected, but no valid trade plan) ────────────────────
    for rejection in selection_result.rejected:
        asset_id = asset_id_map.get(rejection.symbol)
        if not asset_id:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "scan_run_id": scan_run_id,
                "from_state": prev_states.get(asset_id),
                "to_state": "entry_rejected",
                "reason": rejection.rejection_reason,
                "metadata": {
                    **rejection.metadata,
                    "category": rejection.category,
                    "rank": rejection.rank,
                    "setup_type": rejection.setup_type,
                },
            }
        )

    return rows


# ── Public API ────────────────────────────────────────────────────────────────


def record_initial_transitions(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    filter_result: FilterResult,
    scoring_result: ScoringResult,
    selection_result: SelectionResult,
) -> int:
    """Write asset_state_history rows for every asset processed this scan run.

    Covers selected candidates, hard-filtered exclusions, and watchlist assets.
    The 'alerted' transition is NOT written here — that is handled by
    record_alerted_transition() which is called by run_alerter() after each
    successful Discord POST.

    Returns:
        Number of rows inserted.
    """
    all_asset_ids = list(asset_id_map.values())
    prev_states = _resolve_previous_states(client, all_asset_ids)

    rows = _build_transition_rows(
        scan_run_id,
        asset_id_map,
        prev_states,
        filter_result,
        scoring_result,
        selection_result,
    )
    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), _BATCH_SIZE):
        chunk = rows[i : i + _BATCH_SIZE]
        resp = client.table("asset_state_history").insert(chunk).execute()
        total += len(resp.data) if resp.data else len(chunk)

    log.info(
        "record_initial_transitions: %d rows inserted "
        "(%d candidates, %d excluded, %d watchlist, %d low_score, %d entry_rejected)",
        total,
        len(selection_result.all_candidates),
        len(filter_result.exclusions),
        len(scoring_result.watchlist),
        len(scoring_result.low_score),
        len(selection_result.rejected),
    )
    return total


def record_alerted_transition(
    client: Client,
    scan_run_id: str,
    asset_id: str,
    from_state: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write a single candidate_* → alerted transition row.

    Called by run_alerter() immediately after a successful Discord POST.

    Args:
        from_state: 'candidate_clean' or 'candidate_ugly'.
        metadata:   Optional context snapshot (symbol, rank, score_total, etc.).
    """
    row: dict[str, Any] = {
        "asset_id": asset_id,
        "scan_run_id": scan_run_id,
        "from_state": from_state,
        "to_state": "alerted",
        "reason": "alerted",
        "metadata": metadata,
    }
    client.table("asset_state_history").insert(row).execute()
    log.debug("record_alerted_transition: asset_id=%s  %s → alerted", asset_id, from_state)
