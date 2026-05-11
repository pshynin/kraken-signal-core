"""Run Persister — PR 10.

Writes all pipeline stage outputs to Supabase after the pipeline completes.
This is the ONLY module that touches the Supabase SDK outside of db.py.

Write order (preserves FK dependencies):
    1. scan_runs row — created at pipeline START (status='running')
    2. market_snapshots — one row per hard-filter-passed asset
    3. indicator_snapshots — three rows per asset (4h, 1h, 30m)
    4. candidate_scores — all assets: scored + hard-filtered (excluded)
    5. candidate_recommendations — clean + ugly candidates only

Foreign key chain:
    scan_runs ← market_snapshots     (scan_run_id)
    scan_runs ← indicator_snapshots  (scan_run_id)
    scan_runs ← candidate_scores     (scan_run_id)
    assets    ← all tables           (asset_id)
    candidate_scores ← candidate_recommendations (score_id)

Public API
──────────
    create_scan_run(client, triggered_by, scanner_version) -> str   # call BEFORE stages
    fail_scan_run(client, scan_run_id, error_message)               # call on early exit
    complete_scan_run(client, scan_run_id, *, ...)                  # call AFTER persist_run
    persist_run(client, scan_run_id, *, filter_result, ...)         # call after Stage 6
    timeout_stale_scan_runs(client, timeout_minutes) -> int         # call BEFORE create_scan_run

Internal (exposed for unit tests):
    fetch_asset_id_map(client, symbols)             -> dict[str, str]
    upsert_market_snapshots(...)                    -> int
    upsert_indicator_snapshots(...)                 -> int
    upsert_candidate_scores(...)                    -> dict[str, str]   symbol → score_id
    upsert_candidate_recommendations(...)           -> int
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from supabase import Client

from scanner.models import (
    AssetIndicators,
    FilterResult,
    MarketMetrics,
    ScoringResult,
    SelectionResult,
)

log = logging.getLogger(__name__)

_BATCH_SIZE = 200  # max rows per Supabase upsert call


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _batch_upsert(client: Client, table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
    """Upsert rows in batches; returns total row count from responses."""
    total = 0
    for i in range(0, len(rows), _BATCH_SIZE):
        chunk = rows[i : i + _BATCH_SIZE]
        resp = client.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        total += len(resp.data) if resp.data else len(chunk)
    return total


# ── scan_runs lifecycle ───────────────────────────────────────────────────────


def timeout_stale_scan_runs(client: Client, timeout_minutes: int) -> int:
    """Mark stuck running scan_runs as timed_out.

    Only affects rows where ALL three conditions hold:
        - status = 'running'
        - completed_at IS NULL  (a finalized row can never be stuck)
        - started_at < now() − timeout_minutes

    Intentionally does not touch rows that may still be in progress;
    the threshold is the sole guard. Increase scanner.run_timeout_minutes
    in strategy_settings if legitimate runs take longer.

    Args:
        client:          Supabase service-role client.
        timeout_minutes: Configurable threshold from scanner.run_timeout_minutes.

    Returns:
        Number of rows updated (0 when none are stuck).
    """
    cutoff = (datetime.now(UTC) - timedelta(minutes=timeout_minutes)).isoformat()
    resp = (
        client.table("scan_runs")
        .update(
            {
                "status": "timed_out",
                "error_message": (
                    f"auto-timed-out: no completion recorded within {timeout_minutes}m"
                ),
            }
        )
        .eq("status", "running")
        .is_("completed_at", "null")
        .lt("started_at", cutoff)
        .execute()
    )
    n = len(resp.data) if resp.data else 0
    if n:
        log.warning(
            "timeout_stale_scan_runs: marked %d stuck run(s) as timed_out (threshold=%dm)",
            n,
            timeout_minutes,
        )
    return n


def create_scan_run(
    client: Client,
    triggered_by: str = "manual",
    scanner_version: str | None = None,
) -> str:
    """Insert a new scan_run row with status='running'.

    Call this BEFORE the pipeline stages begin so every subsequent DB write
    can reference the returned UUID as scan_run_id.

    Args:
        client:          Supabase service-role client.
        triggered_by:    'schedule' (GitHub Actions cron) or 'manual'.
        scanner_version: Git SHA of the running code, or None.

    Returns:
        The UUID assigned to the new scan_run row.
    """
    row: dict[str, Any] = {
        "started_at": _now_iso(),
        "status": "running",
        "triggered_by": triggered_by,
    }
    if scanner_version is not None:
        row["scanner_version"] = scanner_version

    resp = client.table("scan_runs").insert(row).execute()
    data = cast(list[dict[str, Any]], resp.data)
    scan_run_id: str = str(data[0]["id"])
    log.info("create_scan_run: id=%s  triggered_by=%s", scan_run_id, triggered_by)
    return scan_run_id


def fail_scan_run(client: Client, scan_run_id: str, error_message: str) -> None:
    """Mark a scan_run as 'failed' with an error message."""
    complete_scan_run(client, scan_run_id, status="failed", error_message=error_message)


def complete_scan_run(
    client: Client,
    scan_run_id: str,
    *,
    status: str = "completed",
    assets_scanned: int = 0,
    assets_passed_filter: int = 0,
    candidates_clean: int = 0,
    candidates_ugly: int = 0,
    alerts_sent: int = 0,
    error_message: str | None = None,
) -> None:
    """Update the scan_run row with final counts and status.

    Call this AFTER persist_run() completes (or after fail_scan_run()).

    Args:
        status:               'completed' | 'failed' | 'partial'.
        assets_scanned:       Total universe size (Stage 2 input count).
        assets_passed_filter: Assets surviving the hard filter (Stage 4 output).
        candidates_clean:     Final clean candidate count.
        candidates_ugly:      Final ugly candidate count.
        alerts_sent:          Discord alerts dispatched (0 until PR 11).
        error_message:        Top-level error string when status='failed'.
    """
    update: dict[str, Any] = {
        "completed_at": _now_iso(),
        "status": status,
        "assets_scanned": assets_scanned,
        "assets_passed_filter": assets_passed_filter,
        "candidates_clean": candidates_clean,
        "candidates_ugly": candidates_ugly,
        "alerts_sent": alerts_sent,
    }
    if error_message is not None:
        update["error_message"] = error_message

    client.table("scan_runs").update(update).eq("id", scan_run_id).execute()
    log.info(
        "complete_scan_run: id=%s  status=%s  clean=%d  ugly=%d",
        scan_run_id,
        status,
        candidates_clean,
        candidates_ugly,
    )


# ── Asset ID resolution ───────────────────────────────────────────────────────


def fetch_asset_id_map(client: Client, symbols: list[str]) -> dict[str, str]:
    """Fetch {symbol: asset_id} for the given symbol list.

    Uses the assets.symbol unique index (not kraken_pair) because excluded
    assets in HardFilterResult only carry a symbol, not a kraken_pair.

    Returns an empty dict if symbols is empty or no rows are found.
    """
    if not symbols:
        return {}

    resp = client.table("assets").select("id, symbol").in_("symbol", symbols).execute()
    rows = cast(list[dict[str, Any]], resp.data or [])
    mapping: dict[str, str] = {str(row["symbol"]): str(row["id"]) for row in rows}
    missing = len(symbols) - len(mapping)
    if missing:
        log.warning(
            "fetch_asset_id_map: %d/%d symbols not found in assets table "
            "(run upsert_assets first or check universe coverage)",
            missing,
            len(symbols),
        )
    return mapping


# ── market_snapshots ──────────────────────────────────────────────────────────


def upsert_market_snapshots(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    passed_metrics: list[MarketMetrics],
) -> int:
    """Write market_snapshots rows for all hard-filter-passed assets.

    Args:
        passed_metrics: FilterResult.passed_metrics from run_hard_filter().

    Returns:
        Number of rows written.
    """
    if not passed_metrics:
        return 0

    rows: list[dict[str, Any]] = []
    skipped = 0

    for m in passed_metrics:
        asset_id = asset_id_map.get(m.symbol)
        if asset_id is None:
            log.warning("upsert_market_snapshots: no asset_id for %s — skipping", m.symbol)
            skipped += 1
            continue

        rows.append(
            {
                "scan_run_id": scan_run_id,
                "asset_id": asset_id,
                "snapshot_time": m.snapshot_time or _now_iso(),
                "price_usd": m.price_usd,
                "price_btc": m.price_btc,
                "volume_24h_usd": m.volume_24h_usd,
                "volume_7d_avg_usd": m.volume_7d_avg_usd,
                "volume_ratio_20d": m.volume_ratio_20d,
                "return_3d": m.return_3d,
                "return_7d": m.return_7d,
                "return_14d": m.return_14d,
                "return_vs_btc_7d": m.return_vs_btc_7d,
                "dist_from_7d_high": m.dist_from_7d_high,
                "dist_from_20d_high": m.dist_from_20d_high,
                "spread_pct": m.spread_pct,
                "atr_pct_7d": m.atr_pct_7d,
            }
        )

    if not rows:
        return 0

    count = _batch_upsert(client, "market_snapshots", rows, "scan_run_id,asset_id")
    log.info(
        "upsert_market_snapshots: %d rows written, %d skipped (no asset_id)",
        count,
        skipped,
    )
    return count


# ── indicator_snapshots ───────────────────────────────────────────────────────


def _indicator_snap_row(
    scan_run_id: str,
    asset_id: str,
    snap: Any,
) -> dict[str, Any]:
    """Build one indicator_snapshots row from an IndicatorSnapshot."""
    return {
        "scan_run_id": scan_run_id,
        "asset_id": asset_id,
        "timeframe": snap.timeframe,
        "snapshot_time": snap.snapshot_time or _now_iso(),
        "ema_20": snap.ema_20,
        "ema_50": snap.ema_50,
        "ema_200": snap.ema_200,
        "price_vs_ema20_pct": snap.price_vs_ema20_pct,
        "price_vs_ema50_pct": snap.price_vs_ema50_pct,
        "price_vs_ema200_pct": snap.price_vs_ema200_pct,
        "vwap": snap.vwap,
        "price_vs_vwap_pct": snap.price_vs_vwap_pct,
        "rsi_14": snap.rsi_14,
        "atr_14": snap.atr_14,
        "atr_14_pct": snap.atr_14_pct,
        "volume_ma_20": snap.volume_ma_20,
        "volume_current": snap.volume_current,
        "trend_state": snap.trend_state,
        "ema_alignment": snap.ema_alignment,
        "vwap_state": snap.vwap_state,
    }


def upsert_indicator_snapshots(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    passed_indicators: list[AssetIndicators],
) -> int:
    """Write indicator_snapshots rows — three per asset (4h, 1h, 30m).

    Args:
        passed_indicators: FilterResult.passed_indicators from run_hard_filter().

    Returns:
        Number of rows written.
    """
    if not passed_indicators:
        return 0

    rows: list[dict[str, Any]] = []
    skipped = 0

    for ind in passed_indicators:
        asset_id = asset_id_map.get(ind.symbol)
        if asset_id is None:
            log.warning("upsert_indicator_snapshots: no asset_id for %s — skipping", ind.symbol)
            skipped += 1
            continue
        for snap in (ind.tf_4h, ind.tf_1h, ind.tf_30m):
            rows.append(_indicator_snap_row(scan_run_id, asset_id, snap))

    if not rows:
        return 0

    count = _batch_upsert(client, "indicator_snapshots", rows, "scan_run_id,asset_id,timeframe")
    log.info(
        "upsert_indicator_snapshots: %d rows written (%d assets, %d skipped)",
        count,
        len(passed_indicators) - skipped,
        skipped,
    )
    return count


# ── candidate_scores ──────────────────────────────────────────────────────────


def upsert_candidate_scores(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    scoring_result: ScoringResult,
    filter_result: FilterResult,
) -> dict[str, str]:
    """Write candidate_scores rows for ALL processed assets.

    Includes both:
        - Scored assets (from ScoringResult.scores) with full breakdowns.
        - Hard-filtered assets (from FilterResult.exclusions) with
          category='excluded', all score fields NULL, exclusion_reason set.

    Also populates rank_in_category for clean (rank by score within clean)
    and ugly (rank by score within ugly).

    Returns:
        {symbol: score_id} mapping needed by upsert_candidate_recommendations.
        Built from the upsert response data.
    """
    rows: list[dict[str, Any]] = []

    # ── Rank maps: 1 = best within category ───────────────────────────────────
    rank_map: dict[str, int] = {}
    for rank, score_bd in enumerate(scoring_result.clean, start=1):
        rank_map[score_bd.symbol] = rank
    for rank, score_bd in enumerate(scoring_result.ugly, start=1):
        rank_map[score_bd.symbol] = rank

    # ── Rows for scored assets ─────────────────────────────────────────────────
    for score_bd in scoring_result.scores:
        asset_id = asset_id_map.get(score_bd.symbol)
        if asset_id is None:
            log.warning("upsert_candidate_scores: no asset_id for %s — skipping", score_bd.symbol)
            continue
        rows.append(
            {
                "scan_run_id": scan_run_id,
                "asset_id": asset_id,
                "category": score_bd.category,
                "exclusion_reason": None,
                "score_total": score_bd.score_total,
                "score_liquidity": score_bd.score_liquidity,
                "score_upside": score_bd.score_upside,
                "score_volatility": score_bd.score_volatility,
                "score_structure": score_bd.score_structure,
                "score_rel_strength": score_bd.score_rel_strength,
                "score_volume": score_bd.score_volume,
                "score_catalyst": score_bd.score_catalyst,
                "score_supply_risk": score_bd.score_supply_risk,
                "score_execution": score_bd.score_execution,
                "probability_pct": score_bd.probability_pct,
                "rank_in_category": rank_map.get(score_bd.symbol),
            }
        )

    # ── Rows for hard-filtered (excluded) assets ───────────────────────────────
    for hfr in filter_result.exclusions:
        asset_id = asset_id_map.get(hfr.symbol)
        if asset_id is None:
            log.warning(
                "upsert_candidate_scores (excluded): no asset_id for %s — skipping", hfr.symbol
            )
            continue
        rows.append(
            {
                "scan_run_id": scan_run_id,
                "asset_id": asset_id,
                "category": "excluded",
                "exclusion_reason": hfr.exclusion_reason,
                "score_total": None,
                "score_liquidity": None,
                "score_upside": None,
                "score_volatility": None,
                "score_structure": None,
                "score_rel_strength": None,
                "score_volume": None,
                "score_catalyst": None,
                "score_supply_risk": None,
                "score_execution": None,
                "probability_pct": None,
                "rank_in_category": None,
            }
        )

    if not rows:
        return {}

    resp = (
        client.table("candidate_scores").upsert(rows, on_conflict="scan_run_id,asset_id").execute()
    )
    log.info(
        "upsert_candidate_scores: %d rows (%d scored, %d excluded)",
        len(rows),
        len(scoring_result.scores),
        len(filter_result.exclusions),
    )

    # ── Build {symbol: score_id} from upsert response ─────────────────────────
    asset_id_to_symbol: dict[str, str] = {v: k for k, v in asset_id_map.items()}
    resp_rows = cast(list[dict[str, Any]], resp.data or [])
    score_id_map: dict[str, str] = {
        asset_id_to_symbol[str(row["asset_id"])]: str(row["id"])
        for row in resp_rows
        if row.get("id") and str(row.get("asset_id")) in asset_id_to_symbol
    }

    if not score_id_map:
        log.warning(
            "upsert_candidate_scores: empty score_id_map — candidate_recommendations "
            "will be skipped. Check Supabase returning headers."
        )

    return score_id_map


# ── candidate_recommendations ─────────────────────────────────────────────────


def upsert_candidate_recommendations(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    score_id_map: dict[str, str],
    selection_result: SelectionResult,
) -> int:
    """Write candidate_recommendations rows for clean + ugly candidates only.

    Requires score_id_map populated by upsert_candidate_scores (score_id is
    a NOT NULL FK to candidate_scores.id).

    Args:
        score_id_map: {symbol: score_uuid} returned by upsert_candidate_scores.

    Returns:
        Number of rows written.
    """
    if selection_result.total_count == 0:
        return 0

    rows: list[dict[str, Any]] = []
    skipped = 0

    for candidate in selection_result.all_candidates:
        asset_id = asset_id_map.get(candidate.symbol)
        score_id = score_id_map.get(candidate.symbol)

        if asset_id is None:
            log.warning(
                "upsert_candidate_recommendations: no asset_id for %s — skipping",
                candidate.symbol,
            )
            skipped += 1
            continue
        if score_id is None:
            log.warning(
                "upsert_candidate_recommendations: no score_id for %s — skipping",
                candidate.symbol,
            )
            skipped += 1
            continue

        tp = candidate.trade
        rows.append(
            {
                "scan_run_id": scan_run_id,
                "asset_id": asset_id,
                "score_id": score_id,
                "category": candidate.category,  # 'clean' | 'ugly'
                "rank": candidate.rank,
                "entry_price": tp.entry_price,
                "entry_price_low": tp.entry_price_low,
                "entry_price_high": tp.entry_price_high,
                "exit_price": tp.exit_price,
                "stop_loss": tp.stop_loss,
                "suggested_size_bucket": tp.suggested_size_bucket,
                "probability_pct": candidate.score.probability_pct,
                "expected_gain_pct": tp.expected_gain_pct,
                "reward_risk_ratio": tp.reward_risk_ratio,
                "notes": tp.notes,
                "market_price_at_scan": tp.current_price,
                "state": f"candidate_{candidate.category}",  # 'candidate_clean' | 'candidate_ugly'
            }
        )

    if not rows:
        return 0

    count = _batch_upsert(client, "candidate_recommendations", rows, "scan_run_id,asset_id")
    log.info(
        "upsert_candidate_recommendations: %d rows, %d skipped",
        count,
        skipped,
    )
    return count


# ── Pipeline entry point ──────────────────────────────────────────────────────


def persist_run(
    client: Client,
    scan_run_id: str,
    *,
    filter_result: FilterResult,
    scoring_result: ScoringResult,
    selection_result: SelectionResult,
) -> dict[str, str]:
    """Execute all DB write operations for a completed scan run.

    Write order preserves FK dependencies:
        market_snapshots → indicator_snapshots → candidate_scores
        → candidate_recommendations

    Call complete_scan_run() AFTER this function returns.
    Call fail_scan_run() if this function raises.

    Args:
        scan_run_id:      UUID returned by create_scan_run().
        filter_result:    Output of run_hard_filter() (PR 7).
        scoring_result:   Output of run_scoring_engine() (PR 8).
        selection_result: Output of run_candidate_selector() (PR 9).
    """
    all_symbols = list(
        {
            *(m.symbol for m in filter_result.passed_metrics),
            *(hfr.symbol for hfr in filter_result.exclusions),
        }
    )

    if not all_symbols:
        log.warning("persist_run: no symbols to persist — skipping DB writes")
        return {}

    log.info("persist_run: resolving asset_ids for %d symbols", len(all_symbols))
    asset_id_map = fetch_asset_id_map(client, all_symbols)

    if not asset_id_map:
        log.error(
            "persist_run: asset_id_map is empty — ensure upsert_assets() "
            "ran before persist_run() (Stage 1 DB write must not be skipped)"
        )
        return {}

    upsert_market_snapshots(client, scan_run_id, asset_id_map, filter_result.passed_metrics)
    upsert_indicator_snapshots(client, scan_run_id, asset_id_map, filter_result.passed_indicators)
    score_id_map = upsert_candidate_scores(
        client, scan_run_id, asset_id_map, scoring_result, filter_result
    )
    upsert_candidate_recommendations(
        client, scan_run_id, asset_id_map, score_id_map, selection_result
    )

    # ── State machine: record initial transitions ──────────────────────────────
    from scanner.state_machine import record_initial_transitions

    record_initial_transitions(
        client, scan_run_id, asset_id_map, filter_result, scoring_result, selection_result
    )

    log.info("persist_run complete for scan_run_id=%s", scan_run_id)
    return asset_id_map
