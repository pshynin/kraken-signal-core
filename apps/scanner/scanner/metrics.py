"""Market Metrics — PR 7.

Computes per-asset market metrics from raw 4h OHLCV candle data.

Public API:
    compute_market_metrics(
        bundle:        AssetOHLCV,
        indicator:     AssetIndicators,
        btc_return_7d: float | None = None,
    ) -> MarketMetrics

All returns are fractional (0.08 = +8%). All distances are fractional and
negative when current price is below the reference level.

Candle index arithmetic (4h candles):
    1 day   =   6 candles
    3 days  =  18 candles
    7 days  =  42 candles
    14 days =  84 candles
    20 days = 120 candles

Calculations use only 4h candles (the structural timeframe). 1h and 30m
candles carry insufficient history for meaningful return/volume lookbacks.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from scanner.models import AssetIndicators, AssetOHLCV, MarketMetrics

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CANDLES_PER_DAY: int = 6  # 24h / 4h
CANDLES_3D: int = CANDLES_PER_DAY * 3  # 18
CANDLES_7D: int = CANDLES_PER_DAY * 7  # 42
CANDLES_14D: int = CANDLES_PER_DAY * 14  # 84
CANDLES_20D: int = CANDLES_PER_DAY * 20  # 120


# ── Internal helpers ──────────────────────────────────────────────────────────


def _safe_return(closes: pd.Series, lookback: int) -> float | None:
    """Fractional return over `lookback` candles ending at iloc[-1].

    Formula: (close[-1] - close[-lookback-1]) / close[-lookback-1]
    Returns None when insufficient candles or zero denominator.
    """
    if len(closes) <= lookback:
        return None
    past = float(closes.iloc[-(lookback + 1)])
    current = float(closes.iloc[-1])
    return (current - past) / past if past != 0 else None


def _dist_from_rolling_high(
    closes: pd.Series,
    highs: pd.Series,
    lookback: int,
) -> float | None:
    """(current_close - max_high_over_lookback) / max_high_over_lookback.

    Always <= 0 (price can never exceed the period's high).
    Returns None when insufficient candles.
    """
    if len(highs) < lookback:
        return None
    rolling_high = float(highs.iloc[-lookback:].max())
    current_close = float(closes.iloc[-1])
    return (current_close - rolling_high) / rolling_high if rolling_high != 0 else None


def _spread_proxy(highs: pd.Series, lows: pd.Series, closes: pd.Series, n: int) -> float | None:
    """Mean (high - low) / close over the last n candles — OHLC bid-ask spread proxy."""
    n = min(n, len(highs))
    if n == 0:
        return None
    h = highs.iloc[-n:].to_numpy(dtype=float)
    lo = lows.iloc[-n:].to_numpy(dtype=float)
    cl_raw = closes.iloc[-n:].to_numpy(dtype=float)
    cl_safe: np.ndarray = np.where(cl_raw == 0, np.nan, cl_raw)
    spread = (h - lo) / cl_safe
    result = float(pd.Series(spread).mean())
    return None if pd.isna(result) else result


# ── Public API ────────────────────────────────────────────────────────────────


def compute_market_metrics(
    bundle: AssetOHLCV,
    indicator: AssetIndicators,
    btc_return_7d: float | None = None,
) -> MarketMetrics:
    """Compute all market metrics for one asset from its 4h OHLCV candles.

    Args:
        bundle:        AssetOHLCV from the fetcher (PR 5).
        indicator:     AssetIndicators from the indicator engine (PR 6).
                       Used to reuse the already-computed ATR 14 on 4h.
        btc_return_7d: BTC 7-day fractional return, used for return_vs_btc_7d.
                       Pass None if BTC is not in the universe.

    Returns:
        MarketMetrics with all computable fields populated (None where insufficient data).
    """
    candles = bundle.candles_4h

    _empty = MarketMetrics(
        symbol=bundle.symbol,
        kraken_pair=bundle.kraken_pair,
        snapshot_time="",
        price_usd=0.0,
        price_btc=None,
        volume_24h_usd=None,
        volume_7d_avg_usd=None,
        volume_ratio_20d=None,
        return_3d=None,
        return_7d=None,
        return_14d=None,
        return_vs_btc_7d=None,
        dist_from_7d_high=None,
        dist_from_20d_high=None,
        spread_pct=None,
        atr_pct_7d=None,
    )

    if not candles:
        log.debug("%s: no 4h candles — returning empty MarketMetrics", bundle.symbol)
        return _empty

    closes = pd.Series([c.close for c in candles], dtype=float)
    highs = pd.Series([c.high for c in candles], dtype=float)
    lows = pd.Series([c.low for c in candles], dtype=float)
    volumes = pd.Series([c.volume for c in candles], dtype=float)

    price = float(closes.iloc[-1])
    snapshot_time = pd.Timestamp(int(candles[-1].timestamp), unit="ms", tz="UTC").isoformat()

    # ── Volume (USD = volume_base × close_price) ───────────────────────────────
    usd_vol = volumes * closes

    n = len(usd_vol)
    volume_24h = float(usd_vol.iloc[-CANDLES_PER_DAY:].sum()) if n >= CANDLES_PER_DAY else None
    volume_7d_avg = float(usd_vol.iloc[-CANDLES_7D:].sum() / 7) if n >= CANDLES_7D else None
    avg_20d_daily = float(usd_vol.iloc[-CANDLES_20D:].sum() / 20) if n >= CANDLES_20D else None
    volume_ratio_20d = (
        volume_24h / avg_20d_daily
        if volume_24h is not None and avg_20d_daily is not None and avg_20d_daily > 0
        else None
    )

    # ── Returns (fractional) ───────────────────────────────────────────────────
    return_3d = _safe_return(closes, CANDLES_3D)
    return_7d = _safe_return(closes, CANDLES_7D)
    return_14d = _safe_return(closes, CANDLES_14D)
    return_vs_btc_7d = (
        (return_7d - btc_return_7d) if return_7d is not None and btc_return_7d is not None else None
    )

    # ── Distance from rolling highs ────────────────────────────────────────────
    dist_7d = _dist_from_rolling_high(closes, highs, CANDLES_7D)
    dist_20d = _dist_from_rolling_high(closes, highs, CANDLES_20D)

    # ── Execution quality proxies ──────────────────────────────────────────────
    spread_pct = _spread_proxy(highs, lows, closes, CANDLES_PER_DAY)
    atr_pct_7d = indicator.tf_4h.atr_14_pct  # ATR 14 on 4h; see migration 0004 comment

    log.debug(
        "%s: price=%.4f, vol24h=%.0f, ret7d=%s, trend=%s",
        bundle.symbol,
        price,
        volume_24h or 0,
        f"{return_7d:.2%}" if return_7d is not None else "n/a",
        indicator.tf_4h.trend_state or "n/a",
    )

    return MarketMetrics(
        symbol=bundle.symbol,
        kraken_pair=bundle.kraken_pair,
        snapshot_time=snapshot_time,
        price_usd=price,
        price_btc=None,  # populated in PR 10 once BTC price is resolved
        volume_24h_usd=volume_24h,
        volume_7d_avg_usd=volume_7d_avg,
        volume_ratio_20d=volume_ratio_20d,
        return_3d=return_3d,
        return_7d=return_7d,
        return_14d=return_14d,
        return_vs_btc_7d=return_vs_btc_7d,
        dist_from_7d_high=dist_7d,
        dist_from_20d_high=dist_20d,
        spread_pct=spread_pct,
        atr_pct_7d=atr_pct_7d,
    )
