"""Unit tests for scanner.state_machine — asset_state_history writes.

All tests are offline: Supabase client replaced with MagicMock.
Tests verify row shapes, reason logic, prev-state resolution,
and that INSERT is called with the correct data.
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
from scanner.state_machine import (
    _build_transition_rows,
    _resolve_previous_states,
    record_alerted_transition,
    record_initial_transitions,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _snap(symbol: str = "BTC", timeframe: str = "4h") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        snapshot_time="",
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
    s = _snap(symbol)
    return AssetIndicators(symbol=symbol, kraken_pair=f"{symbol}USD", tf_4h=s, tf_1h=s, tf_30m=s)


def _metrics(symbol: str = "BTC", price: float = 50_000.0) -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="",
        price_usd=price,
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
        current_price=51_000.0,
        distance_to_entry_pct=-1.96,
        setup_type="pullback",
        preferred_entry=50_000.0,
        max_entry=50_500.0,
        support_anchor_type="ema_20",
        support_anchor_value=49_875.0,
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


def _client(history_data: list[dict] | None = None) -> MagicMock:
    client = MagicMock()
    table = client.table.return_value
    # SELECT chain: .select().in_().order().limit().execute()
    select_resp = MagicMock()
    select_resp.data = history_data or []
    (
        table.select.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value
    ) = select_resp
    # INSERT chain: .insert().execute()
    insert_resp = MagicMock()
    insert_resp.data = [{"id": "hist-uuid"}]
    table.insert.return_value.execute.return_value = insert_resp
    return client


# ── _resolve_previous_states ──────────────────────────────────────────────────


def test_resolve_previous_states_returns_most_recent() -> None:
    data = [
        {"asset_id": "uuid-btc", "to_state": "candidate_clean"},
        {"asset_id": "uuid-btc", "to_state": "watchlist"},  # older — should be ignored
        {"asset_id": "uuid-eth", "to_state": "excluded"},
    ]
    client = _client(history_data=data)
    result = _resolve_previous_states(client, ["uuid-btc", "uuid-eth"])
    assert result["uuid-btc"] == "candidate_clean"
    assert result["uuid-eth"] == "excluded"


def test_resolve_previous_states_empty_asset_ids() -> None:
    client = _client()
    result = _resolve_previous_states(client, [])
    assert result == {}
    client.table.assert_not_called()


# ── _build_transition_rows ────────────────────────────────────────────────────


def _make_inputs(
    clean_syms: list[str] | None = None,
    ugly_syms: list[str] | None = None,
    excluded_syms: list[str] | None = None,
    watchlist_syms: list[str] | None = None,
) -> tuple[dict[str, str], FilterResult, ScoringResult, SelectionResult]:
    asset_id_map = {}
    all_syms = (
        (clean_syms or []) + (ugly_syms or []) + (excluded_syms or []) + (watchlist_syms or [])
    )
    for sym in all_syms:
        asset_id_map[sym] = f"uuid-{sym.lower()}"

    fr = FilterResult(
        passed_metrics=[],
        passed_indicators=[],
        exclusions=[
            HardFilterResult(symbol=s, passed=False, exclusion_reason="insufficient_volume_24h")
            for s in (excluded_syms or [])
        ],
    )
    scores: list[ScoreBreakdown] = []
    for s in clean_syms or []:
        scores.append(_score(s, "clean"))
    for s in ugly_syms or []:
        scores.append(_score(s, "ugly"))
    for s in watchlist_syms or []:
        scores.append(_score(s, "watchlist"))
    sr = ScoringResult(scores=scores)
    sel = SelectionResult(
        clean=[_candidate(s, "clean", i + 1) for i, s in enumerate(clean_syms or [])],
        ugly=[_candidate(s, "ugly", i + 1) for i, s in enumerate(ugly_syms or [])],
    )
    return asset_id_map, fr, sr, sel


def test_build_transition_rows_clean_candidate() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(clean_syms=["BTC"])
    rows = _build_transition_rows("run-id", asset_id_map, {}, fr, sr, sel)
    clean_row = next(r for r in rows if r["to_state"] == "candidate_clean")
    assert clean_row["asset_id"] == "uuid-btc"
    assert clean_row["reason"] == "new_candidate"


def test_build_transition_rows_ugly_candidate() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(ugly_syms=["ETH"])
    rows = _build_transition_rows("run-id", asset_id_map, {}, fr, sr, sel)
    ugly_row = next(r for r in rows if r["to_state"] == "candidate_ugly")
    assert ugly_row["asset_id"] == "uuid-eth"


def test_build_transition_rows_excluded() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(excluded_syms=["SOL"])
    rows = _build_transition_rows("run-id", asset_id_map, {}, fr, sr, sel)
    exc_row = next(r for r in rows if r["to_state"] == "excluded")
    assert exc_row["reason"] == "insufficient_volume_24h"
    assert exc_row["metadata"] is None


def test_build_transition_rows_watchlist() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(watchlist_syms=["AVAX"])
    rows = _build_transition_rows("run-id", asset_id_map, {}, fr, sr, sel)
    wl_row = next(r for r in rows if r["to_state"] == "watchlist")
    assert wl_row["reason"] == "watchlist_entry"
    assert wl_row["metadata"] is not None
    assert "score_total" in wl_row["metadata"]


def test_build_transition_rows_retained_candidate() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(clean_syms=["BTC"])
    prev = {"uuid-btc": "candidate_clean"}  # same state as this run
    rows = _build_transition_rows("run-id", asset_id_map, prev, fr, sr, sel)
    clean_row = next(r for r in rows if r["to_state"] == "candidate_clean")
    assert clean_row["reason"] == "retained_candidate"
    assert clean_row["from_state"] == "candidate_clean"


def test_build_transition_rows_metadata_contains_price() -> None:
    asset_id_map, fr, sr, sel = _make_inputs(clean_syms=["BTC"])
    rows = _build_transition_rows("run-id", asset_id_map, {}, fr, sr, sel)
    meta = rows[0]["metadata"]
    assert meta is not None
    assert "price_usd" in meta
    assert "rank" in meta


# ── record_initial_transitions ────────────────────────────────────────────────


def test_record_initial_transitions_calls_insert() -> None:
    client = _client()
    asset_id_map, fr, sr, sel = _make_inputs(clean_syms=["BTC"], excluded_syms=["ETH"])
    count = record_initial_transitions(client, "run-id", asset_id_map, fr, sr, sel)
    assert count > 0
    client.table.return_value.insert.assert_called()


# ── record_alerted_transition ─────────────────────────────────────────────────


def test_record_alerted_transition_inserts_alerted_state() -> None:
    client = _client()
    record_alerted_transition(
        client,
        "run-id",
        "uuid-btc",
        from_state="candidate_clean",
        metadata={"symbol": "BTC", "rank": 1},
    )
    inserted = client.table.return_value.insert.call_args[0][0]
    assert inserted["to_state"] == "alerted"
    assert inserted["from_state"] == "candidate_clean"
    assert inserted["reason"] == "alerted"
