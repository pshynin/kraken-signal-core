"""Unit tests for scanner.scoring — 9-factor scoring engine.

All tests are offline: no HTTP, no ccxt, no Supabase.
Sub-scorers are tested in isolation; run_scoring_engine is tested end-to-end.
"""

from __future__ import annotations

import pytest

from scanner.models import (
    AssetIndicators,
    FilterResult,
    IndicatorSnapshot,
    MarketMetrics,
    ScoreBreakdown,
)
from scanner.scoring import (
    ScoringConfig,
    _assign_category,
    _probability_pct,
    _score_catalyst,
    _score_execution,
    _score_liquidity,
    _score_rel_strength,
    _score_structure,
    _score_supply_risk,
    _score_upside,
    _score_volatility,
    _score_volume,
    run_scoring_engine,
    score_asset,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

_DEFAULT_CFG = ScoringConfig()


def _snap(
    rsi_14: float | None = 60.0,
    atr_14_pct: float | None = 8.0,
    price_vs_ema20_pct: float | None = 3.0,
    trend_state: str | None = "up",
    ema_alignment: str | None = "bullish",
    vwap_state: str | None = "above",
    volume_current: float | None = 1200.0,
    volume_ma_20: float | None = 1000.0,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="X",
        timeframe="4h",
        snapshot_time="",
        ema_20=None,
        ema_50=None,
        ema_200=None,
        price_vs_ema20_pct=price_vs_ema20_pct,
        price_vs_ema50_pct=None,
        price_vs_ema200_pct=None,
        vwap=None,
        price_vs_vwap_pct=None,
        rsi_14=rsi_14,
        atr_14=None,
        atr_14_pct=atr_14_pct,
        volume_ma_20=volume_ma_20,
        volume_current=volume_current,
        trend_state=trend_state,
        ema_alignment=ema_alignment,
        vwap_state=vwap_state,
    )


def _indicator(symbol: str = "BTC", **kwargs: object) -> AssetIndicators:
    s = _snap(**kwargs)  # type: ignore[arg-type]
    return AssetIndicators(symbol=symbol, kraken_pair=f"{symbol}USD", tf_4h=s, tf_1h=s, tf_30m=s)


def _metrics(
    symbol: str = "BTC",
    price_usd: float = 50_000.0,
    volume_24h_usd: float = 10_000_000.0,
    volume_7d_avg_usd: float = 8_000_000.0,
    volume_ratio_20d: float = 1.4,
    return_3d: float = 0.07,
    return_7d: float = 0.12,
    return_14d: float = 0.18,
    return_vs_btc_7d: float | None = 0.06,
    dist_from_7d_high: float = -0.10,
    dist_from_20d_high: float = -0.18,
    spread_pct: float = 0.008,
    atr_pct_7d: float = 8.0,
) -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="",
        price_usd=price_usd,
        price_btc=None,
        volume_24h_usd=volume_24h_usd,
        volume_7d_avg_usd=volume_7d_avg_usd,
        volume_ratio_20d=volume_ratio_20d,
        return_3d=return_3d,
        return_7d=return_7d,
        return_14d=return_14d,
        return_vs_btc_7d=return_vs_btc_7d,
        dist_from_7d_high=dist_from_7d_high,
        dist_from_20d_high=dist_from_20d_high,
        spread_pct=spread_pct,
        atr_pct_7d=atr_pct_7d,
    )


def _filter_result(
    pairs: list[tuple[MarketMetrics, AssetIndicators]] | None = None,
) -> FilterResult:
    pairs = pairs or [(_metrics("BTC"), _indicator("BTC"))]
    return FilterResult(
        passed_metrics=[p[0] for p in pairs],
        passed_indicators=[p[1] for p in pairs],
        exclusions=[],
    )


# ── _score_liquidity ──────────────────────────────────────────────────────────


def test_score_liquidity_high_volume_near_max() -> None:
    m = _metrics(volume_24h_usd=25_000_000, volume_7d_avg_usd=20_000_000, spread_pct=0.003)
    score = _score_liquidity(m)
    assert score >= 18.0


def test_score_liquidity_low_volume_low_score() -> None:
    m = _metrics(volume_24h_usd=400_000, volume_7d_avg_usd=800_000, spread_pct=0.05)
    score = _score_liquidity(m)
    assert score <= 6.0


def test_score_liquidity_capped_at_20() -> None:
    m = _metrics(volume_24h_usd=100_000_000, volume_7d_avg_usd=100_000_000, spread_pct=0.001)
    assert _score_liquidity(m) == pytest.approx(20.0)


# ── _score_upside ─────────────────────────────────────────────────────────────


def test_score_upside_sweet_spot() -> None:
    m = _metrics(dist_from_7d_high=-0.10, return_7d=0.12)
    score = _score_upside(m, _indicator(rsi_14=60.0))
    assert score >= 12.0  # 6 (dist) + 5 (RSI) + 4 (return7d) = 15 max


def test_score_upside_overbought_rsi() -> None:
    low = _score_upside(_metrics(), _indicator(rsi_14=76.0))
    high = _score_upside(_metrics(), _indicator(rsi_14=60.0))
    assert low < high


def test_score_upside_negative_return() -> None:
    score = _score_upside(_metrics(return_7d=-0.10), _indicator())
    assert score < _score_upside(_metrics(return_7d=0.12), _indicator())


# ── _score_volatility ─────────────────────────────────────────────────────────


def test_score_volatility_optimal_atr() -> None:
    assert _score_volatility(_metrics(atr_pct_7d=8.0)) == pytest.approx(10.0)


def test_score_volatility_low_atr_penalized() -> None:
    assert _score_volatility(_metrics(atr_pct_7d=3.0)) < _score_volatility(_metrics(atr_pct_7d=8.0))


def test_score_volatility_none_returns_neutral() -> None:
    assert _score_volatility(_metrics(atr_pct_7d=None)) == pytest.approx(5.0)


# ── _score_structure ──────────────────────────────────────────────────────────


def test_score_structure_strong_up_bullish_near_max() -> None:
    ind = _indicator(trend_state="strong_up", ema_alignment="bullish", vwap_state="above")
    score = _score_structure(ind)
    assert score >= 13.0  # 6+5+2+2=15 possible with 1h alignment


def test_score_structure_bearish_near_zero() -> None:
    ind = _indicator(trend_state="strong_down", ema_alignment="bearish", vwap_state="below")
    score = _score_structure(ind)
    assert score <= 2.0


def test_score_structure_capped_at_15() -> None:
    ind = _indicator(trend_state="strong_up", ema_alignment="bullish", vwap_state="above")
    assert _score_structure(ind) <= 15.0


# ── _score_rel_strength ───────────────────────────────────────────────────────


def test_score_rel_strength_outperforming_btc() -> None:
    assert _score_rel_strength(_metrics(return_vs_btc_7d=0.12)) == pytest.approx(10.0)


def test_score_rel_strength_underperforming_btc() -> None:
    assert _score_rel_strength(_metrics(return_vs_btc_7d=-0.08)) == pytest.approx(0.0)


def test_score_rel_strength_no_btc_fallback() -> None:
    score = _score_rel_strength(_metrics(return_vs_btc_7d=None, return_7d=0.12))
    assert 5.0 < score <= 10.0  # fallback to absolute return


# ── _score_volume ─────────────────────────────────────────────────────────────


def test_score_volume_expansion_high() -> None:
    m = _metrics(volume_ratio_20d=2.0)
    ind = _indicator(volume_current=2000.0, volume_ma_20=1000.0)
    score = _score_volume(m, ind)
    assert score == pytest.approx(10.0)


def test_score_volume_contraction_low() -> None:
    m = _metrics(volume_ratio_20d=0.5)
    ind = _indicator(volume_current=500.0, volume_ma_20=1000.0)
    score = _score_volume(m, ind)
    assert score <= 3.0


# ── _score_catalyst ───────────────────────────────────────────────────────────


def test_score_catalyst_momentum_setup() -> None:
    m = _metrics(return_3d=0.08, dist_from_7d_high=-0.06)
    ind = _indicator(trend_state="up", vwap_state="reclaiming")
    assert _score_catalyst(m, ind) >= 8.0  # 5 (ret3) + 3 (vwap+trend) + 2 (dist)


def test_score_catalyst_declining_low() -> None:
    m = _metrics(return_3d=-0.10, dist_from_7d_high=-0.40)
    ind = _indicator(trend_state="down", vwap_state="below")
    assert _score_catalyst(m, ind) <= 2.0


# ── _score_supply_risk ────────────────────────────────────────────────────────


def test_score_supply_risk_far_below_high() -> None:
    assert _score_supply_risk(_metrics(dist_from_20d_high=-0.30)) == pytest.approx(5.0)


def test_score_supply_risk_at_high() -> None:
    assert _score_supply_risk(_metrics(dist_from_20d_high=-0.01)) == pytest.approx(1.0)


def test_score_supply_risk_none_neutral() -> None:
    assert _score_supply_risk(_metrics(dist_from_20d_high=None)) == pytest.approx(3.0)


# ── _score_execution ──────────────────────────────────────────────────────────


def test_score_execution_price_near_ema20() -> None:
    assert _score_execution(_metrics(), _indicator(price_vs_ema20_pct=3.0)) == pytest.approx(5.0)


def test_score_execution_overextended_lower() -> None:
    low = _score_execution(_metrics(), _indicator(price_vs_ema20_pct=18.0))
    high = _score_execution(_metrics(), _indicator(price_vs_ema20_pct=3.0))
    assert low < high


# ── _probability_pct ──────────────────────────────────────────────────────────


def test_probability_pct_tier_85() -> None:
    assert _probability_pct(87.0) == pytest.approx(90.0)


def test_probability_pct_tier_78() -> None:
    assert _probability_pct(80.0) == pytest.approx(84.0)


def test_probability_pct_tier_70() -> None:
    assert _probability_pct(72.0) == pytest.approx(77.0)


def test_probability_pct_tier_62() -> None:
    assert _probability_pct(65.0) == pytest.approx(69.0)


def test_probability_pct_below_floor() -> None:
    assert _probability_pct(50.0) is None


# ── _assign_category ──────────────────────────────────────────────────────────


def test_assign_category_clean() -> None:
    m = _metrics(
        volume_24h_usd=3_000_000,
        volume_7d_avg_usd=6_000_000,
        return_3d=0.08,
        return_vs_btc_7d=0.05,
    )
    ind = _indicator(rsi_14=60.0, price_vs_ema20_pct=5.0)
    cat = _assign_category(74.0, m, ind, _DEFAULT_CFG)
    assert cat == "clean"


def test_assign_category_clean_blocked_by_low_volume() -> None:
    m = _metrics(volume_24h_usd=500_000, volume_7d_avg_usd=800_000)
    ind = _indicator(rsi_14=60.0)
    cat = _assign_category(74.0, m, ind, _DEFAULT_CFG)
    assert cat in ("ugly", "watchlist")


def test_assign_category_ugly() -> None:
    m = _metrics(volume_24h_usd=500_000, volume_7d_avg_usd=800_000)
    ind = _indicator(rsi_14=65.0)
    cat = _assign_category(65.0, m, ind, _DEFAULT_CFG)
    assert cat == "ugly"


def test_assign_category_watchlist() -> None:
    cat = _assign_category(58.0, _metrics(), _indicator(rsi_14=40.0), _DEFAULT_CFG)
    assert cat == "watchlist"


# ── score_asset ───────────────────────────────────────────────────────────────


def test_score_total_sums_components() -> None:
    m = _metrics()
    ind = _indicator()
    bd = score_asset(m, ind, _DEFAULT_CFG)
    component_sum = round(
        bd.score_liquidity
        + bd.score_upside
        + bd.score_volatility
        + bd.score_structure
        + bd.score_rel_strength
        + bd.score_volume
        + bd.score_catalyst
        + bd.score_supply_risk
        + bd.score_execution,
        2,
    )
    assert bd.score_total == pytest.approx(component_sum, abs=0.01)


def test_score_total_bounded_0_to_100() -> None:
    for rsi in [48.0, 55.0, 65.0, 78.0]:
        for atr in [4.0, 8.0, 20.0]:
            bd = score_asset(_metrics(atr_pct_7d=atr), _indicator(rsi_14=rsi), _DEFAULT_CFG)
            assert 0.0 <= bd.score_total <= 100.0


def test_score_asset_returns_score_breakdown() -> None:
    bd = score_asset(_metrics(), _indicator(), _DEFAULT_CFG)
    assert isinstance(bd, ScoreBreakdown)
    assert bd.exclusion_reason is None


# ── run_scoring_engine ────────────────────────────────────────────────────────


def test_run_scoring_engine_empty() -> None:
    result = run_scoring_engine(FilterResult())
    assert result.scores == []
    assert result.clean_count == 0


def test_run_scoring_engine_sorted_by_score_desc() -> None:
    low_m = _metrics("LOW", volume_24h_usd=400_000, volume_7d_avg_usd=800_000, atr_pct_7d=3.0)
    pairs = [
        (low_m, _indicator("LOW")),
        (_metrics("HIGH"), _indicator("HIGH")),
        (_metrics("MID", volume_24h_usd=2_000_000, volume_7d_avg_usd=3_000_000), _indicator("MID")),
    ]
    result = run_scoring_engine(_filter_result(pairs))
    scores = [s.score_total for s in result.scores]
    assert scores == sorted(scores, reverse=True)


def test_run_scoring_engine_classifies_correctly() -> None:
    good_metrics = _metrics(
        "GOOD",
        volume_24h_usd=10_000_000,
        volume_7d_avg_usd=9_000_000,
        return_3d=0.08,
        dist_from_7d_high=-0.10,
        dist_from_20d_high=-0.20,
    )
    good_ind = _indicator(
        "GOOD",
        rsi_14=60.0,
        atr_14_pct=9.0,
        trend_state="strong_up",
        ema_alignment="bullish",
        vwap_state="above",
        price_vs_ema20_pct=3.0,
    )
    result = run_scoring_engine(_filter_result([(good_metrics, good_ind)]))
    assert len(result.scores) == 1
    assert result.scores[0].category in ("clean", "ugly", "watchlist")


def test_run_scoring_engine_preserves_all_assets() -> None:
    pairs = [
        (_metrics("A"), _indicator("A")),
        (_metrics("B"), _indicator("B")),
        (_metrics("C"), _indicator("C")),
    ]
    result = run_scoring_engine(_filter_result(pairs))
    assert len(result.scores) == 3
