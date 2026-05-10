"""Unit tests for scanner.metrics — market metrics computation.

All tests are offline: no HTTP, no ccxt, no Supabase.
Deterministic OHLCV data is generated in-process for each test.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from scanner.metrics import (
    CANDLES_3D,
    CANDLES_7D,
    CANDLES_PER_DAY,
    _dist_from_rolling_high,
    _safe_return,
    compute_market_metrics,
)
from scanner.models import AssetIndicators, AssetOHLCV, IndicatorSnapshot, OHLCVCandle

# ── Helpers ───────────────────────────────────────────────────────────────────

_4H_MS = 4 * 3600 * 1_000
_START_TS = 1_700_000_000_000


def _make_candles(n: int, start_price: float = 100.0, drift: float = 0.002) -> list[OHLCVCandle]:
    candles = []
    price = start_price
    for i in range(n):
        c = price * (1 + drift)
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


def _stub_snapshot(
    atr_14_pct: float | None = 5.0,
    rsi_14: float | None = 60.0,
    price_vs_ema20_pct: float | None = 3.0,
    trend_state: str | None = "up",
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="BTC",
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


def _stub_indicator(symbol: str = "BTC", **snap_kwargs: object) -> AssetIndicators:
    snap = _stub_snapshot(**snap_kwargs)  # type: ignore[arg-type]
    return AssetIndicators(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        tf_4h=snap,
        tf_1h=snap,
        tf_30m=snap,
    )


def _make_bundle(symbol: str = "BTC", n: int = 250, drift: float = 0.002) -> AssetOHLCV:
    candles = _make_candles(n, drift=drift)
    return AssetOHLCV(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        candles_4h=candles,
        candles_1h=candles,
        candles_30m=candles,
        fetched_at="",
    )


# ── _safe_return ──────────────────────────────────────────────────────────────


def test_safe_return_basic() -> None:
    closes = pd.Series([100.0, 110.0])
    result = _safe_return(closes, lookback=1)
    assert result == pytest.approx(0.10)


def test_safe_return_insufficient() -> None:
    closes = pd.Series([100.0, 110.0])
    assert _safe_return(closes, lookback=5) is None


def test_safe_return_zero_denominator() -> None:
    closes = pd.Series([0.0, 100.0])
    assert _safe_return(closes, lookback=1) is None


# ── _dist_from_rolling_high ───────────────────────────────────────────────────


def test_dist_from_rolling_high_at_high() -> None:
    closes = pd.Series([100.0, 105.0, 110.0])
    highs = pd.Series([100.0, 105.0, 110.0])
    result = _dist_from_rolling_high(closes, highs, 3)
    assert result == pytest.approx(0.0)


def test_dist_from_rolling_high_below() -> None:
    closes = pd.Series([100.0, 105.0, 100.0])
    highs = pd.Series([100.0, 105.0, 100.0])
    result = _dist_from_rolling_high(closes, highs, 3)
    assert result == pytest.approx((100.0 - 105.0) / 105.0)
    assert result is not None and result <= 0.0


def test_dist_from_rolling_high_insufficient() -> None:
    closes = pd.Series([100.0])
    highs = pd.Series([105.0])
    assert _dist_from_rolling_high(closes, highs, 7) is None


# ── compute_market_metrics ────────────────────────────────────────────────────


def test_compute_metrics_price_usd() -> None:
    candles = _make_candles(250)
    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator())
    assert metrics.price_usd == pytest.approx(candles[-1].close)


def test_compute_metrics_snapshot_time_matches_last_candle() -> None:
    candles = _make_candles(250)
    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator())
    expected = pd.Timestamp(candles[-1].timestamp, unit="ms", tz="UTC").isoformat()
    assert metrics.snapshot_time == expected


def test_compute_metrics_volume_24h_sums_last_6_candles() -> None:
    candles = _make_candles(250)
    bundle = _make_bundle(n=250)
    metrics = compute_market_metrics(bundle, _stub_indicator())

    manual_24h = sum(c.volume * c.close for c in candles[-CANDLES_PER_DAY:])
    assert metrics.volume_24h_usd == pytest.approx(manual_24h, rel=1e-4)


def test_compute_metrics_volume_7d_avg_is_weekly_average() -> None:
    candles = _make_candles(250)
    manual_7d_total = sum(c.volume * c.close for c in candles[-CANDLES_7D:])
    manual_7d_avg = manual_7d_total / 7.0

    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator())
    assert metrics.volume_7d_avg_usd == pytest.approx(manual_7d_avg, rel=1e-4)


def test_compute_metrics_volume_ratio_20d_reasonable() -> None:
    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator())
    assert metrics.volume_ratio_20d is not None
    assert metrics.volume_ratio_20d > 0


def test_compute_metrics_return_3d_fractional() -> None:
    candles = _make_candles(250)
    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator())

    past = candles[-(CANDLES_3D + 1)].close
    manual = (candles[-1].close - past) / past
    assert metrics.return_3d == pytest.approx(manual, rel=1e-4)


def test_compute_metrics_return_7d_positive_in_uptrend() -> None:
    metrics = compute_market_metrics(_make_bundle(n=250, drift=0.002), _stub_indicator())
    assert metrics.return_7d is not None and metrics.return_7d > 0


def test_compute_metrics_return_vs_btc_uses_btc_return() -> None:
    bundle = _make_bundle("SOL", n=250)
    indicator = _stub_indicator("SOL")
    metrics = compute_market_metrics(bundle, indicator, btc_return_7d=0.05)

    assert metrics.return_vs_btc_7d is not None
    expected = metrics.return_7d - 0.05  # type: ignore[operator]
    assert metrics.return_vs_btc_7d == pytest.approx(expected, rel=1e-4)


def test_compute_metrics_return_vs_btc_none_when_no_btc() -> None:
    metrics = compute_market_metrics(_make_bundle(n=250), _stub_indicator(), btc_return_7d=None)
    assert metrics.return_vs_btc_7d is None


def test_compute_metrics_dist_from_7d_high_non_positive() -> None:
    metrics = compute_market_metrics(_make_bundle(n=250, drift=0.002), _stub_indicator())
    assert metrics.dist_from_7d_high is not None
    assert metrics.dist_from_7d_high <= 0.0


def test_compute_metrics_atr_reuses_indicator() -> None:
    indicator = _stub_indicator(atr_14_pct=7.5)
    metrics = compute_market_metrics(_make_bundle(n=250), indicator)
    assert metrics.atr_pct_7d == pytest.approx(7.5)


def test_compute_metrics_empty_candles_returns_zeroed() -> None:
    empty = AssetOHLCV(
        symbol="BTC",
        kraken_pair="XXBTZUSD",
        candles_4h=[],
        candles_1h=[],
        candles_30m=[],
        fetched_at="",
    )
    metrics = compute_market_metrics(empty, _stub_indicator())
    assert metrics.price_usd == 0.0
    assert metrics.return_3d is None
    assert metrics.volume_24h_usd is None


def test_compute_metrics_insufficient_candles_for_14d_return() -> None:
    metrics = compute_market_metrics(_make_bundle(n=CANDLES_7D + 1), _stub_indicator())
    assert metrics.return_7d is not None
    assert metrics.return_14d is None
