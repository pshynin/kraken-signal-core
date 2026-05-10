"""Unit tests for scanner.indicators — the indicator computation engine.

All tests are offline: no HTTP, no ccxt, no Supabase.
Synthetic OHLCV candles are generated in-process for each test.

Coverage:
    _candles_to_df     — DataFrame shape, column types
    _safe_last         — NaN/empty/None handling
    _trend_state       — all 5 branches (strong_up, up, neutral, down, strong_down)
    _ema_alignment     — all 4 branches (bullish, partial_bullish, neutral, bearish)
    _vwap_state        — all 3 branches (above, reclaiming, below)
    compute_indicators — sufficient / insufficient / empty candle sets
    run_indicator_engine — all success / partial failure / empty
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from scanner.indicators import (
    _candles_to_df,
    _ema_alignment,
    _safe_last,
    _trend_state,
    _vwap_state,
    compute_indicators,
    run_indicator_engine,
)
from scanner.models import (
    AssetOHLCV,
    IndicatorSnapshot,
    OHLCVCandle,
)

# ── Candle generators ─────────────────────────────────────────────────────────

_4H_MS = 4 * 3600 * 1_000
_START_TS = 1_700_000_000_000  # Nov 2023, arbitrary


def _make_candles(
    n: int,
    start_price: float = 100.0,
    drift: float = 0.003,
    base_volume: float = 1_000.0,
) -> list[OHLCVCandle]:
    """Generate n synthetic candles with a gentle uptrend (drift per candle).

    drift=0.003 → +0.3% per candle. After 250 candles price is ~~211.
    EMAs converge to a bullish stack after ~220 candles.
    """
    candles: list[OHLCVCandle] = []
    price = start_price
    for i in range(n):
        o = price
        c = price * (1 + drift)
        h = c * 1.005
        lo = o * 0.995
        vol = base_volume * (1 + 0.1 * math.sin(i))
        candles.append(
            OHLCVCandle(
                timestamp=_START_TS + i * _4H_MS,
                open=round(o, 4),
                high=round(h, 4),
                low=round(lo, 4),
                close=round(c, 4),
                volume=round(vol, 4),
            )
        )
        price = c
    return candles


def _make_declining_candles(n: int, start_price: float = 200.0) -> list[OHLCVCandle]:
    """Generate n candles with a steady downtrend (-0.4% per candle)."""
    return _make_candles(n, start_price=start_price, drift=-0.004)


def _make_bundle(
    symbol: str = "BTC",
    n: int = 250,
    drift: float = 0.003,
) -> AssetOHLCV:
    candles = _make_candles(n, drift=drift)
    return AssetOHLCV(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        candles_4h=candles,
        candles_1h=candles,
        candles_30m=candles,
        fetched_at="2026-01-01T00:00:00+00:00",
    )


# ── _candles_to_df ────────────────────────────────────────────────────────────


def test_candles_to_df_shape() -> None:
    candles = _make_candles(50)
    df = _candles_to_df(candles)
    assert df.shape == (50, 6)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_candles_to_df_dtypes() -> None:
    df = _candles_to_df(_make_candles(10))
    assert df["close"].dtype == float
    assert df["volume"].dtype == float


def test_candles_to_df_empty() -> None:
    df = _candles_to_df([])
    assert df.empty
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


# ── _safe_last ────────────────────────────────────────────────────────────────


def test_safe_last_normal() -> None:
    s = pd.Series([1.0, 2.0, 3.0])
    assert _safe_last(s) == pytest.approx(3.0)


def test_safe_last_with_nans() -> None:
    s = pd.Series([float("nan"), 5.0, float("nan")])
    assert _safe_last(s) == pytest.approx(5.0)


def test_safe_last_all_nan() -> None:
    s = pd.Series([float("nan"), float("nan")])
    assert _safe_last(s) is None


def test_safe_last_empty_series() -> None:
    assert _safe_last(pd.Series([], dtype=float)) is None


def test_safe_last_none_input() -> None:
    assert _safe_last(None) is None


# ── _trend_state ──────────────────────────────────────────────────────────────


def test_trend_state_strong_up() -> None:
    assert _trend_state(110.0, ema20=108.0, ema50=105.0, ema200=100.0) == "strong_up"


def test_trend_state_up() -> None:
    assert _trend_state(108.0, ema20=109.0, ema50=105.0, ema200=100.0) == "up"


def test_trend_state_neutral_above_200() -> None:
    assert _trend_state(102.0, ema20=104.0, ema50=105.0, ema200=100.0) == "neutral"


def test_trend_state_down() -> None:
    assert _trend_state(95.0, ema20=94.0, ema50=90.0, ema200=100.0) == "down"


def test_trend_state_strong_down() -> None:
    assert _trend_state(85.0, ema20=87.0, ema50=90.0, ema200=100.0) == "strong_down"


def test_trend_state_neutral_no_ema200() -> None:
    assert _trend_state(110.0, ema20=108.0, ema50=105.0, ema200=None) == "neutral"


# ── _ema_alignment ────────────────────────────────────────────────────────────


def test_ema_alignment_bullish() -> None:
    assert _ema_alignment(110.0, ema20=108.0, ema50=105.0, ema200=100.0) == "bullish"


def test_ema_alignment_partial_bullish_ema_stacked_price_below_ema20() -> None:
    assert _ema_alignment(106.0, ema20=108.0, ema50=105.0, ema200=100.0) == "partial_bullish"


def test_ema_alignment_partial_bullish_price_above_ema50() -> None:
    assert _ema_alignment(108.0, ema20=104.0, ema50=105.0, ema200=100.0) == "partial_bullish"


def test_ema_alignment_bearish() -> None:
    assert _ema_alignment(85.0, ema20=90.0, ema50=95.0, ema200=100.0) == "bearish"


def test_ema_alignment_neutral_no_ema200() -> None:
    assert _ema_alignment(110.0, ema20=108.0, ema50=105.0, ema200=None) == "neutral"


def test_ema_alignment_neutral_mixed() -> None:
    assert _ema_alignment(102.0, ema20=100.0, ema50=105.0, ema200=100.0) == "neutral"


# ── _vwap_state ───────────────────────────────────────────────────────────────


def test_vwap_state_above() -> None:
    assert _vwap_state(1.5) == "above"


def test_vwap_state_reclaiming_positive() -> None:
    assert _vwap_state(0.3) == "reclaiming"


def test_vwap_state_reclaiming_negative() -> None:
    assert _vwap_state(-0.3) == "reclaiming"


def test_vwap_state_reclaiming_zero() -> None:
    assert _vwap_state(0.0) == "reclaiming"


def test_vwap_state_below() -> None:
    assert _vwap_state(-1.0) == "below"


def test_vwap_state_none() -> None:
    assert _vwap_state(None) == "below"


# ── compute_indicators ────────────────────────────────────────────────────────


def test_compute_indicators_returns_snapshot() -> None:
    snap = compute_indicators("BTC", "4h", _make_candles(250))
    assert isinstance(snap, IndicatorSnapshot)
    assert snap.symbol == "BTC"
    assert snap.timeframe == "4h"


def test_compute_indicators_sufficient_candles_non_none() -> None:
    """With 250 candles, all indicators except optionally EMA200 should be non-None."""
    snap = compute_indicators("BTC", "4h", _make_candles(250))
    assert snap.ema_20 is not None
    assert snap.ema_50 is not None
    assert snap.rsi_14 is not None
    assert snap.atr_14 is not None
    assert snap.atr_14_pct is not None
    assert snap.volume_ma_20 is not None
    assert snap.volume_current is not None
    assert snap.vwap is not None


def test_compute_indicators_ema200_available_with_250_candles() -> None:
    snap = compute_indicators("BTC", "4h", _make_candles(250))
    assert snap.ema_200 is not None


def test_compute_indicators_ema200_none_with_150_candles() -> None:
    """EMA 200 requires 200+ candles; 150 is insufficient."""
    snap = compute_indicators("BTC", "4h", _make_candles(150))
    assert snap.ema_200 is None
    assert snap.ema_20 is not None
    assert snap.ema_50 is not None


def test_compute_indicators_ema50_none_with_40_candles() -> None:
    snap = compute_indicators("BTC", "4h", _make_candles(40))
    assert snap.ema_50 is None
    assert snap.ema_200 is None
    assert snap.ema_20 is not None


def test_compute_indicators_empty_returns_none_fields() -> None:
    snap = compute_indicators("BTC", "4h", [])
    assert snap.ema_20 is None
    assert snap.rsi_14 is None
    assert snap.trend_state is None
    assert snap.snapshot_time == ""


def test_compute_indicators_rsi_in_range() -> None:
    snap = compute_indicators("BTC", "4h", _make_candles(50))
    if snap.rsi_14 is not None:
        assert 0.0 <= snap.rsi_14 <= 100.0


def test_compute_indicators_atr_positive() -> None:
    snap = compute_indicators("BTC", "4h", _make_candles(50))
    if snap.atr_14 is not None:
        assert snap.atr_14 > 0.0
        assert snap.atr_14_pct is not None
        assert snap.atr_14_pct > 0.0


def test_compute_indicators_snapshot_time_matches_last_candle() -> None:
    candles = _make_candles(50)
    snap = compute_indicators("BTC", "4h", candles)
    last_ts_ms = candles[-1].timestamp
    expected_ts = pd.Timestamp(last_ts_ms, unit="ms", tz="UTC").isoformat()
    assert snap.snapshot_time == expected_ts


def test_compute_indicators_uptrend_classification() -> None:
    """250-candle uptrend should produce a bullish trend_state."""
    snap = compute_indicators("BTC", "4h", _make_candles(250, drift=0.003))
    assert snap.trend_state in ("strong_up", "up")


def test_compute_indicators_downtrend_classification() -> None:
    """250-candle downtrend should produce a bearish trend_state."""
    snap = compute_indicators("BTC", "4h", _make_declining_candles(250))
    assert snap.trend_state in ("down", "strong_down")


def test_compute_indicators_state_strings_valid() -> None:
    """All non-None state values must match DB CHECK constraints."""
    valid_trends = {"strong_up", "up", "neutral", "down", "strong_down"}
    valid_alignment = {"bullish", "partial_bullish", "neutral", "bearish"}
    valid_vwap = {"above", "reclaiming", "below"}

    snap = compute_indicators("SOL", "1h", _make_candles(250))
    if snap.trend_state is not None:
        assert snap.trend_state in valid_trends
    if snap.ema_alignment is not None:
        assert snap.ema_alignment in valid_alignment
    if snap.vwap_state is not None:
        assert snap.vwap_state in valid_vwap


# ── run_indicator_engine ──────────────────────────────────────────────────────


def test_run_indicator_engine_all_success() -> None:
    bundles = [_make_bundle("BTC"), _make_bundle("SOL"), _make_bundle("ETH")]
    result = run_indicator_engine(bundles)

    assert result.success_count == 3
    assert result.failure_count == 0
    symbols = [a.symbol for a in result.successful]
    assert "BTC" in symbols and "SOL" in symbols


def test_run_indicator_engine_correct_timeframe_routing() -> None:
    """4h candles must appear in tf_4h, not tf_1h."""
    result = run_indicator_engine([_make_bundle("BTC")])
    asset = result.successful[0]

    assert asset.tf_4h.timeframe == "4h"
    assert asset.tf_1h.timeframe == "1h"
    assert asset.tf_30m.timeframe == "30m"


def test_run_indicator_engine_empty() -> None:
    result = run_indicator_engine([])
    assert result.success_count == 0
    assert result.failure_count == 0


def test_run_indicator_engine_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """An asset that raises during compute_indicators goes to failed_symbols."""
    import scanner.indicators as ind

    original_compute = compute_indicators

    def mock_compute(symbol: str, timeframe: str, candles: list) -> IndicatorSnapshot:
        if symbol == "BADCOIN":
            raise RuntimeError("Simulated indicator failure")
        return original_compute(symbol, timeframe, candles)

    monkeypatch.setattr(ind, "compute_indicators", mock_compute)

    bundles = [_make_bundle("SOL"), _make_bundle("BADCOIN"), _make_bundle("ETH")]
    result = run_indicator_engine(bundles)

    assert result.success_count == 2
    assert result.failure_count == 1
    assert "BADCOIN" in result.failed_symbols
    assert "SOL" in [a.symbol for a in result.successful]
    assert "ETH" in [a.symbol for a in result.successful]
