"""Unit tests for scanner.filter — hard filter rule engine.

All tests are offline. No DB, no HTTP.
apply_hard_filter is tested rule-by-rule with manually crafted inputs.
run_hard_filter is tested end-to-end with synthetic bundles + indicators.
"""

from __future__ import annotations

import math

from scanner.filter import HardFilterConfig, apply_hard_filter, run_hard_filter
from scanner.models import (
    AssetIndicators,
    AssetOHLCV,
    IndicatorSnapshot,
    MarketMetrics,
    OHLCVCandle,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_4H_MS = 4 * 3600 * 1_000
_START_TS = 1_700_000_000_000

_DEFAULT_CONFIG = HardFilterConfig()


def _make_candles(n: int, start_price: float = 100.0) -> list[OHLCVCandle]:
    candles = []
    price = start_price
    for i in range(n):
        c = price * 1.002
        candles.append(
            OHLCVCandle(
                timestamp=_START_TS + i * _4H_MS,
                open=round(price, 6),
                high=round(c * 1.005, 6),
                low=round(price * 0.995, 6),
                close=round(c, 6),
                volume=round(1000.0 + 10 * math.sin(i), 4),
            )
        )
        price = c
    return candles


def _snap(
    rsi_14: float | None = 60.0,
    atr_14_pct: float | None = 8.0,
    price_vs_ema20_pct: float | None = 3.0,
    trend_state: str | None = "up",
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
        volume_ma_20=None,
        volume_current=None,
        trend_state=trend_state,
        ema_alignment=None,
        vwap_state=None,
    )


def _indicator(symbol: str = "BTC", **kwargs: object) -> AssetIndicators:
    s = _snap(**kwargs)  # type: ignore[arg-type]
    return AssetIndicators(symbol=symbol, kraken_pair=f"{symbol}USD", tf_4h=s, tf_1h=s, tf_30m=s)


def _good_metrics(symbol: str = "BTC") -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="2026-01-01T00:00:00+00:00",
        price_usd=100.0,
        price_btc=None,
        volume_24h_usd=5_000_000.0,
        volume_7d_avg_usd=4_000_000.0,
        volume_ratio_20d=1.5,
        return_3d=0.05,
        return_7d=0.10,
        return_14d=0.15,
        return_vs_btc_7d=0.03,
        dist_from_7d_high=-0.02,
        dist_from_20d_high=-0.05,
        spread_pct=0.002,
        atr_pct_7d=8.0,
    )


def _bundle(symbol: str = "BTC", n: int = 250) -> AssetOHLCV:
    candles = _make_candles(n)
    return AssetOHLCV(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        candles_4h=candles,
        candles_1h=candles,
        candles_30m=candles,
        fetched_at="",
    )


# ── apply_hard_filter — passes ────────────────────────────────────────────────


def test_apply_filter_passes_good_asset() -> None:
    result = apply_hard_filter(_good_metrics(), _indicator(), _DEFAULT_CONFIG)
    assert result.passed is True
    assert result.exclusion_reason is None


# ── apply_hard_filter — each exclusion rule ───────────────────────────────────


def test_apply_filter_rejects_invalid_price() -> None:
    m = _good_metrics()
    m.price_usd = 0.0
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.passed is False
    assert result.exclusion_reason == "invalid_price"


def test_apply_filter_rejects_insufficient_volume_24h() -> None:
    m = _good_metrics()
    m.volume_24h_usd = 100_000.0  # below 300k floor
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "insufficient_volume_24h"


def test_apply_filter_rejects_volume_24h_none() -> None:
    m = _good_metrics()
    m.volume_24h_usd = None
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "insufficient_volume_24h"


def test_apply_filter_rejects_insufficient_volume_7d() -> None:
    m = _good_metrics()
    m.volume_7d_avg_usd = 500_000.0  # below 750k floor
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "insufficient_volume_7d"


def test_apply_filter_rejects_rsi_below_hard_min() -> None:
    m = _good_metrics()
    result = apply_hard_filter(m, _indicator(rsi_14=45.0), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "rsi_below_hard_min"


def test_apply_filter_rejects_rsi_above_hard_max() -> None:
    m = _good_metrics()
    result = apply_hard_filter(m, _indicator(rsi_14=80.0), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "rsi_above_hard_max"


def test_apply_filter_rsi_none_does_not_exclude() -> None:
    """Missing RSI should not trigger RSI-based exclusion."""
    result = apply_hard_filter(_good_metrics(), _indicator(rsi_14=None), _DEFAULT_CONFIG)
    assert result.passed is True


def test_apply_filter_rejects_extreme_pump_3d() -> None:
    m = _good_metrics()
    m.return_3d = 0.45  # above 40% ceiling
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "extreme_pump_3d"


def test_apply_filter_rejects_overextended_vs_ema20() -> None:
    m = _good_metrics()
    result = apply_hard_filter(m, _indicator(price_vs_ema20_pct=25.0), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "overextended_vs_ema20"


def test_apply_filter_rejects_insufficient_volatility() -> None:
    m = _good_metrics()
    m.atr_pct_7d = 3.0  # below 4% floor
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "insufficient_volatility"


def test_apply_filter_rejects_excessive_volatility() -> None:
    m = _good_metrics()
    m.atr_pct_7d = 35.0  # above 30% ceiling
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.exclusion_reason == "excessive_volatility"


def test_apply_filter_atr_none_does_not_exclude() -> None:
    """Missing ATR should not trigger volatility exclusion."""
    m = _good_metrics()
    m.atr_pct_7d = None
    result = apply_hard_filter(m, _indicator(), _DEFAULT_CONFIG)
    assert result.passed is True


# ── Custom config ─────────────────────────────────────────────────────────────


def test_apply_filter_custom_config_tighter_rsi() -> None:
    strict = HardFilterConfig(rsi_hard_min=55.0)
    m = _good_metrics()
    result = apply_hard_filter(m, _indicator(rsi_14=52.0), strict)
    assert result.exclusion_reason == "rsi_below_hard_min"


# ── run_hard_filter ───────────────────────────────────────────────────────────


def test_run_hard_filter_all_pass() -> None:
    bundles = [_bundle("BTC"), _bundle("SOL"), _bundle("ETH")]
    inds = [_indicator("BTC"), _indicator("SOL"), _indicator("ETH")]
    result = run_hard_filter(bundles, inds)
    assert result.passed_count == 3
    assert result.excluded_count == 0


def test_run_hard_filter_partial_exclusion() -> None:
    """SOL with low RSI should be excluded; others pass."""
    bundles = [_bundle("BTC"), _bundle("SOL"), _bundle("ETH")]
    inds = [
        _indicator("BTC"),
        _indicator("SOL", rsi_14=30.0),  # below rsi_hard_min=48
        _indicator("ETH"),
    ]
    result = run_hard_filter(bundles, inds)
    assert result.passed_count == 2
    assert result.excluded_count == 1
    assert result.exclusions[0].exclusion_reason == "rsi_below_hard_min"


def test_run_hard_filter_no_indicator_excluded() -> None:
    """Bundle with no matching indicator lands in exclusions."""
    bundles = [_bundle("BTC"), _bundle("SOL")]
    inds = [_indicator("BTC")]  # SOL has no indicator
    result = run_hard_filter(bundles, inds)
    assert result.passed_count == 1
    assert any(e.exclusion_reason == "no_indicator" for e in result.exclusions)


def test_run_hard_filter_passed_indicators_co_indexed() -> None:
    """passed_indicators must align with passed_metrics (same symbols, same order)."""
    bundles = [_bundle("BTC"), _bundle("SOL"), _bundle("ETH")]
    inds = [_indicator("BTC"), _indicator("SOL"), _indicator("ETH")]
    result = run_hard_filter(bundles, inds)
    assert len(result.passed_metrics) == len(result.passed_indicators)
    for m, i in zip(result.passed_metrics, result.passed_indicators):
        assert m.symbol == i.symbol


def test_run_hard_filter_empty_bundles() -> None:
    result = run_hard_filter([], [])
    assert result.passed_count == 0
    assert result.excluded_count == 0
    assert result.pass_rate == 0.0
