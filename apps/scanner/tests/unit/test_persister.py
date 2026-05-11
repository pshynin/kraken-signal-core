"""Unit tests for scanner.persister — all DB write functions.

All tests are fully offline: the Supabase client is replaced with a
MagicMock so no network calls occur. Tests verify:
    - Correct table names and SQL operations are invoked.
    - Row shapes (required columns present, correct values).
    - Edge-case handling (missing asset_id, empty inputs, etc.).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from scanner.models import (
    AssetIndicators,
    FilterResult,
    HardFilterResult,
    IndicatorSnapshot,
    MarketMetrics,
    ScoreBreakdown,
    ScoredCandidate,
    ScoringResult,
    SelectionResult,
    TradeParameters,
)
from scanner.persister import (
    complete_scan_run,
    create_scan_run,
    fail_scan_run,
    fetch_asset_id_map,
    persist_run,
    timeout_stale_scan_runs,
    upsert_candidate_recommendations,
    upsert_candidate_scores,
    upsert_indicator_snapshots,
    upsert_market_snapshots,
)

# ── Mock helpers ──────────────────────────────────────────────────────────────


def _client(
    insert_data: list[dict] | None = None,
    select_data: list[dict] | None = None,
    upsert_data: list[dict] | None = None,
) -> MagicMock:
    """Build a MagicMock Supabase client with pre-configured response data."""
    client = MagicMock()
    table = client.table.return_value

    insert_resp = MagicMock()
    insert_resp.data = insert_data or [{"id": "scan-run-uuid"}]
    table.insert.return_value.execute.return_value = insert_resp

    select_resp = MagicMock()
    select_resp.data = select_data or []
    table.select.return_value.in_.return_value.execute.return_value = select_resp
    table.select.return_value.eq.return_value.execute.return_value = select_resp

    upsert_resp = MagicMock()
    upsert_resp.data = upsert_data or []
    table.upsert.return_value.execute.return_value = upsert_resp

    update_resp = MagicMock()
    update_resp.data = []
    table.update.return_value.eq.return_value.execute.return_value = update_resp

    return client


def _snap(symbol: str = "BTC", timeframe: str = "4h") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        snapshot_time="2026-01-01T00:00:00Z",
        ema_20=None,
        ema_50=None,
        ema_200=None,
        price_vs_ema20_pct=3.0,
        price_vs_ema50_pct=None,
        price_vs_ema200_pct=None,
        vwap=None,
        price_vs_vwap_pct=None,
        rsi_14=60.0,
        atr_14=None,
        atr_14_pct=8.0,
        volume_ma_20=1000.0,
        volume_current=1200.0,
        trend_state="up",
        ema_alignment="bullish",
        vwap_state="above",
    )


def _indicator(symbol: str = "BTC") -> AssetIndicators:
    return AssetIndicators(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        tf_4h=_snap(symbol, "4h"),
        tf_1h=_snap(symbol, "1h"),
        tf_30m=_snap(symbol, "30m"),
    )


def _metrics(symbol: str = "BTC") -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="2026-01-01T00:00:00Z",
        price_usd=50_000.0,
        price_btc=None,
        volume_24h_usd=5_000_000.0,
        volume_7d_avg_usd=8_000_000.0,
        volume_ratio_20d=1.4,
        return_3d=0.06,
        return_7d=0.12,
        return_14d=0.18,
        return_vs_btc_7d=0.05,
        dist_from_7d_high=-0.10,
        dist_from_20d_high=-0.15,
        spread_pct=0.008,
        atr_pct_7d=8.0,
    )


def _score(symbol: str = "BTC", category: str = "clean") -> ScoreBreakdown:
    return ScoreBreakdown(
        symbol=symbol,
        category=category,
        exclusion_reason=None,
        score_total=76.0,
        score_liquidity=14.0,
        score_upside=12.0,
        score_volatility=10.0,
        score_structure=13.0,
        score_rel_strength=8.0,
        score_volume=8.0,
        score_catalyst=8.0,
        score_supply_risk=4.0,
        score_execution=4.0,
        probability_pct=77.0,
    )


def _trade(symbol: str = "BTC") -> TradeParameters:
    return TradeParameters(
        symbol=symbol,
        entry_price=50_000.0,
        entry_price_low=49_750.0,
        entry_price_high=50_250.0,
        exit_price=56_000.0,
        stop_loss=47_000.0,
        suggested_size_bucket="5k-10k",
        expected_gain_pct=12.0,
        reward_risk_ratio=2.0,
        notes="trend:up",
    )


def _candidate(symbol: str = "BTC", category: str = "clean", rank: int = 1) -> ScoredCandidate:
    return ScoredCandidate(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        category=category,
        rank=rank,
        score=_score(symbol, category),
        trade=_trade(symbol),
        market=_metrics(symbol),
        indicators=_indicator(symbol),
    )


def _filter_result(
    passed_syms: list[str] | None = None,
    excluded_syms: list[str] | None = None,
) -> FilterResult:
    return FilterResult(
        passed_metrics=[_metrics(s) for s in (passed_syms or ["BTC"])],
        passed_indicators=[_indicator(s) for s in (passed_syms or ["BTC"])],
        exclusions=[
            HardFilterResult(symbol=s, passed=False, exclusion_reason="insufficient_volume_24h")
            for s in (excluded_syms or [])
        ],
    )


def _scoring_result(
    clean: list[str] | None = None,
    ugly: list[str] | None = None,
) -> ScoringResult:
    scores: list[ScoreBreakdown] = []
    for s in clean or ["BTC"]:
        scores.append(_score(s, "clean"))
    for s in ugly or []:
        scores.append(_score(s, "ugly"))
    return ScoringResult(scores=scores)


def _selection_result(
    clean: list[str] | None = None,
    ugly: list[str] | None = None,
) -> SelectionResult:
    return SelectionResult(
        clean=[_candidate(s, "clean", i + 1) for i, s in enumerate(clean or [])],
        ugly=[_candidate(s, "ugly", i + 1) for i, s in enumerate(ugly or [])],
    )


# ── create_scan_run ───────────────────────────────────────────────────────────


def test_create_scan_run_returns_uuid() -> None:
    client = _client(insert_data=[{"id": "test-run-uuid"}])
    result = create_scan_run(client)
    assert result == "test-run-uuid"


def test_create_scan_run_inserts_running_status() -> None:
    client = _client(insert_data=[{"id": "abc"}])
    create_scan_run(client, triggered_by="schedule", scanner_version="abc123")
    row = client.table.return_value.insert.call_args[0][0]
    assert row["status"] == "running"
    assert row["triggered_by"] == "schedule"
    assert row["scanner_version"] == "abc123"


def test_create_scan_run_uses_scan_runs_table() -> None:
    client = _client(insert_data=[{"id": "abc"}])
    create_scan_run(client)
    client.table.assert_called_with("scan_runs")


# ── fail_scan_run / complete_scan_run ─────────────────────────────────────────


def test_complete_scan_run_sets_completed_status() -> None:
    client = _client()
    complete_scan_run(
        client,
        "run-id",
        status="completed",
        assets_scanned=200,
        candidates_clean=5,
        candidates_ugly=3,
    )
    update_payload = client.table.return_value.update.call_args[0][0]
    assert update_payload["status"] == "completed"
    assert update_payload["assets_scanned"] == 200
    assert update_payload["candidates_clean"] == 5
    assert "completed_at" in update_payload


def test_fail_scan_run_sets_failed_with_message() -> None:
    client = _client()
    fail_scan_run(client, "run-id", error_message="Stage 3 crashed")
    update_payload = client.table.return_value.update.call_args[0][0]
    assert update_payload["status"] == "failed"
    assert update_payload["error_message"] == "Stage 3 crashed"


# ── timeout_stale_scan_runs ──────────────────────────────────────────────────


def test_timeout_stale_scan_runs_returns_count() -> None:
    client = _client()
    client.table.return_value.update.return_value.eq.return_value.is_.return_value.lt.return_value.execute.return_value.data = [
        {"id": "stale-run-1"},
        {"id": "stale-run-2"},
    ]
    n = timeout_stale_scan_runs(client, timeout_minutes=120)
    assert n == 2


def test_timeout_stale_scan_runs_zero_when_none_stuck() -> None:
    client = _client()
    client.table.return_value.update.return_value.eq.return_value.is_.return_value.lt.return_value.execute.return_value.data = []
    n = timeout_stale_scan_runs(client, timeout_minutes=120)
    assert n == 0


def test_timeout_stale_scan_runs_filters_correctly() -> None:
    client = _client()
    client.table.return_value.update.return_value.eq.return_value.is_.return_value.lt.return_value.execute.return_value.data = []
    timeout_stale_scan_runs(client, timeout_minutes=60)
    client.table.assert_called_with("scan_runs")
    update_payload = client.table.return_value.update.call_args[0][0]
    assert update_payload["status"] == "timed_out"
    assert "error_message" in update_payload
    assert "60m" in update_payload["error_message"]


def test_timeout_stale_scan_runs_uses_completed_at_null_guard() -> None:
    client = _client()
    client.table.return_value.update.return_value.eq.return_value.is_.return_value.lt.return_value.execute.return_value.data = []
    timeout_stale_scan_runs(client, timeout_minutes=120)
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.is_.assert_called_once_with("completed_at", "null")


# ── fetch_asset_id_map ────────────────────────────────────────────────────────


def test_fetch_asset_id_map_builds_dict() -> None:
    data = [{"symbol": "BTC", "id": "uuid-btc"}, {"symbol": "ETH", "id": "uuid-eth"}]
    client = _client(select_data=data)
    result = fetch_asset_id_map(client, ["BTC", "ETH"])
    assert result == {"BTC": "uuid-btc", "ETH": "uuid-eth"}


def test_fetch_asset_id_map_empty_symbols() -> None:
    client = _client()
    result = fetch_asset_id_map(client, [])
    assert result == {}
    client.table.assert_not_called()


# ── upsert_market_snapshots ───────────────────────────────────────────────────


def test_upsert_market_snapshots_required_columns() -> None:
    client = _client(upsert_data=[{}])
    upsert_market_snapshots(client, "run-id", {"BTC": "asset-uuid"}, [_metrics("BTC")])
    rows = client.table.return_value.upsert.call_args[0][0]
    assert len(rows) == 1
    row = rows[0]
    for col in ("scan_run_id", "asset_id", "price_usd", "snapshot_time", "atr_pct_7d"):
        assert col in row, f"missing column: {col}"
    assert row["scan_run_id"] == "run-id"
    assert row["asset_id"] == "asset-uuid"


def test_upsert_market_snapshots_skips_missing_asset_id() -> None:
    client = _client(upsert_data=[{}])
    # BTC has no asset_id in the map
    count = upsert_market_snapshots(client, "run-id", {}, [_metrics("BTC")])
    assert count == 0
    client.table.return_value.upsert.assert_not_called()


def test_upsert_market_snapshots_empty_returns_zero() -> None:
    client = _client()
    count = upsert_market_snapshots(client, "run-id", {}, [])
    assert count == 0


# ── upsert_indicator_snapshots ────────────────────────────────────────────────


def test_upsert_indicator_snapshots_three_rows_per_asset() -> None:
    client = _client(upsert_data=[{}, {}, {}])
    upsert_indicator_snapshots(client, "run-id", {"BTC": "asset-uuid"}, [_indicator("BTC")])
    rows = client.table.return_value.upsert.call_args[0][0]
    assert len(rows) == 3
    timeframes = {r["timeframe"] for r in rows}
    assert timeframes == {"4h", "1h", "30m"}


def test_upsert_indicator_snapshots_skips_missing_asset_id() -> None:
    client = _client()
    count = upsert_indicator_snapshots(client, "run-id", {}, [_indicator("BTC")])
    assert count == 0
    client.table.return_value.upsert.assert_not_called()


# ── upsert_candidate_scores ───────────────────────────────────────────────────


def test_upsert_candidate_scores_excluded_has_null_score() -> None:
    upsert_data = [
        {"id": "score-uuid-exc", "asset_id": "asset-eth"},
    ]
    client = _client(upsert_data=upsert_data)
    fr = _filter_result(passed_syms=[], excluded_syms=["ETH"])
    sr = ScoringResult()
    upsert_candidate_scores(client, "run-id", {"ETH": "asset-eth"}, sr, fr)
    rows = client.table.return_value.upsert.call_args[0][0]
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "excluded"
    assert row["score_total"] is None
    assert row["exclusion_reason"] == "insufficient_volume_24h"


def test_upsert_candidate_scores_scored_asset_has_values() -> None:
    upsert_data = [{"id": "score-uuid", "asset_id": "asset-btc"}]
    client = _client(upsert_data=upsert_data)
    fr = _filter_result(passed_syms=["BTC"])
    sr = _scoring_result(clean=["BTC"])
    upsert_candidate_scores(client, "run-id", {"BTC": "asset-btc"}, sr, fr)
    rows = client.table.return_value.upsert.call_args[0][0]
    scored_row = next(r for r in rows if r.get("category") != "excluded")
    assert scored_row["category"] == "clean"
    assert scored_row["score_total"] == 76.0
    assert scored_row["rank_in_category"] == 1


def test_upsert_candidate_scores_returns_score_id_map() -> None:
    upsert_data = [{"id": "score-uuid", "asset_id": "asset-btc"}]
    client = _client(upsert_data=upsert_data)
    fr = _filter_result(passed_syms=["BTC"])
    sr = _scoring_result(clean=["BTC"])
    score_id_map = upsert_candidate_scores(client, "run-id", {"BTC": "asset-btc"}, sr, fr)
    assert score_id_map == {"BTC": "score-uuid"}


# ── upsert_candidate_recommendations ─────────────────────────────────────────


def test_upsert_candidate_recommendations_writes_both_categories() -> None:
    client = _client(upsert_data=[{}, {}])
    sel = _selection_result(clean=["BTC"], ugly=["ETH"])
    asset_id_map = {"BTC": "asset-btc", "ETH": "asset-eth"}
    score_id_map = {"BTC": "score-btc", "ETH": "score-eth"}
    upsert_candidate_recommendations(client, "run-id", asset_id_map, score_id_map, sel)
    rows = client.table.return_value.upsert.call_args[0][0]
    assert len(rows) == 2
    categories = {r["category"] for r in rows}
    assert categories == {"clean", "ugly"}


def test_upsert_candidate_recommendations_state_field() -> None:
    client = _client(upsert_data=[{}])
    sel = _selection_result(clean=["BTC"])
    upsert_candidate_recommendations(
        client, "run-id", {"BTC": "asset-btc"}, {"BTC": "score-btc"}, sel
    )
    rows = client.table.return_value.upsert.call_args[0][0]
    assert rows[0]["state"] == "candidate_clean"


def test_upsert_candidate_recommendations_skips_missing_score_id() -> None:
    client = _client()
    sel = _selection_result(clean=["BTC"])
    count = upsert_candidate_recommendations(
        client,
        "run-id",
        {"BTC": "asset-btc"},
        {},
        sel,  # no score_id for BTC
    )
    assert count == 0
    client.table.return_value.upsert.assert_not_called()


def test_upsert_candidate_recommendations_empty_selection() -> None:
    client = _client()
    count = upsert_candidate_recommendations(client, "run-id", {}, {}, SelectionResult())
    assert count == 0


# ── persist_run ───────────────────────────────────────────────────────────────


def test_persist_run_calls_all_four_tables() -> None:
    """persist_run should touch market_snapshots, indicator_snapshots,
    candidate_scores, and candidate_recommendations."""
    upsert_data = [{"id": "score-uuid", "asset_id": "asset-btc"}]
    select_data = [{"symbol": "BTC", "id": "asset-btc"}]
    client = _client(select_data=select_data, upsert_data=upsert_data)

    persist_run(
        client,
        "run-id",
        filter_result=_filter_result(passed_syms=["BTC"]),
        scoring_result=_scoring_result(clean=["BTC"]),
        selection_result=_selection_result(clean=["BTC"]),
    )

    # table() is called at least once for each of the 4 write tables
    called_tables = {c.args[0] for c in client.table.call_args_list}
    assert "market_snapshots" in called_tables
    assert "indicator_snapshots" in called_tables
    assert "candidate_scores" in called_tables
    assert "candidate_recommendations" in called_tables
