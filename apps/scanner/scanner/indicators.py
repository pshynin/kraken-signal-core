"""Indicator Engine — PR 6.

Computes all technical indicators from OHLCV candle data for each asset/timeframe.

Public API:
    run_indicator_engine(bundles: list[AssetOHLCV]) -> IndicatorResult

Internal API (exposed for unit testing):
    compute_indicators(symbol, timeframe, candles) -> IndicatorSnapshot
    _candles_to_df(candles) -> pd.DataFrame
    _safe_last(series) -> float | None
    _trend_state(price, ema20, ema50, ema200) -> str
    _ema_alignment(price, ema20, ema50, ema200) -> str
    _vwap_state(price_vs_vwap_pct) -> str

Indicators computed (per timeframe):
    EMA 20 / 50 / 200     — exponential moving averages of close
    price_vs_ema*_pct     — (price - EMA) / EMA * 100
    VWAP                  — cumulative volume-weighted average price (rolling)
    price_vs_vwap_pct     — (price - VWAP) / VWAP * 100
    RSI 14                — Wilder's RSI of close
    ATR 14                — Average True Range (absolute USD + % of price)
    volume_ma_20          — 20-candle simple moving average of volume
    volume_current        — volume of the last closed candle

Derived state classifications (string, matches DB CHECK constraints):
    trend_state    → strong_up | up | neutral | down | strong_down
    ema_alignment  → bullish | partial_bullish | neutral | bearish
    vwap_state     → above | reclaiming | below

Notes:
    - pandas_ta returns NaN when insufficient candles exist for a period.
      _safe_last() converts NaN → None.
    - VWAP is computed as a rolling cumulative over the entire candle history
      (typical_price * volume) / cumulative_volume. No day-anchor needed for
      the momentum scanner's use case (comparing current price to volume-
      weighted average entry of recent participants).
    - All None fields are valid and expected when a timeframe has < 200 candles.
"""

from __future__ import annotations

import logging

import pandas as pd
import pandas_ta as ta

from scanner.models import AssetIndicators, AssetOHLCV, IndicatorResult, IndicatorSnapshot

log = logging.getLogger(__name__)

# ── DataFrame helpers ─────────────────────────────────────────────────────────


def _candles_to_df(candles: list) -> pd.DataFrame:
    """Convert OHLCVCandle list to a pandas DataFrame.

    Returns DataFrame with columns: timestamp, open, high, low, close, volume.
    Index is integer (0-based). Use _candles_to_df for indicator computation;
    timestamps are available as the 'timestamp' column (Unix ms).
    """
    if not candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    return pd.DataFrame(
        [
            {
                "timestamp": c.timestamp,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]
    )


def _safe_last(series: pd.Series | None) -> float | None:
    """Return the last non-NaN value from a pandas Series, or None.

    pandas_ta returns NaN for indicator periods without enough data.
    This function converts those to Python None for the dataclass fields.
    """
    if series is None or series.empty:
        return None
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _pct_diff(price: float, reference: float | None) -> float | None:
    """(price - reference) / reference * 100. Returns None if reference is None or zero."""
    if reference is None or reference == 0.0:
        return None
    return (price - reference) / reference * 100.0


# ── State classifiers ─────────────────────────────────────────────────────────


def _trend_state(
    price: float,
    ema20: float | None,
    ema50: float | None,
    ema200: float | None,
) -> str:
    """Classify trend state from price position relative to EMAs.

    Hierarchy (highest to lowest precedence):
        strong_up  — price > EMA20 > EMA50 > EMA200  (full bullish stack)
        up         — price > EMA50 > EMA200           (above key MAs)
        neutral    — price > EMA200 but <= EMA50      (above 200, sideways)
        down       — price < EMA200 but > EMA50       (below 200, above 50)
        strong_down — price < EMA200 and <= EMA50     (below both key MAs)

    Returns 'neutral' if EMA200 is unavailable (insufficient candles).
    """
    if ema200 is None:
        return "neutral"

    e50_above_200 = ema50 is not None and ema50 > ema200
    e20_above_50 = ema20 is not None and ema50 is not None and ema20 > ema50

    if e20_above_50 and e50_above_200 and ema20 is not None and price > ema20:
        return "strong_up"

    if e50_above_200 and ema50 is not None and price > ema50:
        return "up"

    if price > ema200:
        return "neutral"

    if ema50 is not None and price > ema50:
        return "down"

    return "strong_down"


def _ema_alignment(
    price: float,
    ema20: float | None,
    ema50: float | None,
    ema200: float | None,
) -> str:
    """Classify EMA alignment (price + EMA relative ordering).

    bullish        — price > EMA20 > EMA50 > EMA200  (ideal long setup)
    partial_bullish — EMAs bullishly stacked but price pulled back below EMA20,
                      OR price > EMA50 > EMA200 but EMA20 not yet > EMA50
    bearish        — price < EMA200, EMA20 < EMA50 < EMA200 (full bear)
    neutral        — mixed / insufficient data

    Returns 'neutral' if EMA200 is unavailable.
    """
    if ema200 is None:
        return "neutral"

    if ema20 is not None and ema50 is not None:
        e20_gt_50 = ema20 > ema50
        e50_gt_200 = ema50 > ema200

        if price > ema20 and e20_gt_50 and e50_gt_200:
            return "bullish"

        if e20_gt_50 and e50_gt_200:
            return "partial_bullish"

        if e50_gt_200 and price > ema50:
            return "partial_bullish"

        if ema20 < ema50 and not e50_gt_200 and price < ema200:
            return "bearish"
    else:
        if ema50 is not None and ema50 > ema200 and price > ema50:
            return "partial_bullish"
        if price < ema200:
            return "bearish"

    return "neutral"


def _vwap_state(price_vs_vwap_pct: float | None) -> str:
    """Classify price position relative to VWAP.

    above      — price more than 0.5% above VWAP
    reclaiming — price within ±0.5% of VWAP (transition zone)
    below      — price more than 0.5% below VWAP

    Returns 'below' when VWAP is unavailable (conservative default).
    """
    if price_vs_vwap_pct is None:
        return "below"
    if price_vs_vwap_pct > 0.5:
        return "above"
    if price_vs_vwap_pct >= -0.5:
        return "reclaiming"
    return "below"


# ── Rolling VWAP ──────────────────────────────────────────────────────────────


def _compute_rolling_vwap(df: pd.DataFrame) -> pd.Series:
    """Compute rolling (cumulative) VWAP from the start of the DataFrame.

    Formula: cumsum(typical_price * volume) / cumsum(volume)
    typical_price = (high + low + close) / 3

    This gives the volume-weighted average price of all participants over the
    entire candle history in the DataFrame. Used to determine whether the
    current price is above or below the aggregate entry price of recent holders.

    Returns a Series with NaN where cumulative volume is zero.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, float("nan"))
    return vwap


# ── Core computation ──────────────────────────────────────────────────────────


def compute_indicators(
    symbol: str,
    timeframe: str,
    candles: list,
) -> IndicatorSnapshot:
    """Compute all technical indicators for one asset/timeframe.

    Args:
        symbol:    Asset ticker, e.g. "BTC".
        timeframe: One of '4h', '1h', '30m'.
        candles:   list[OHLCVCandle] from the fetcher.

    Returns:
        IndicatorSnapshot with all fields populated (None where insufficient data).
    """
    df = _candles_to_df(candles)

    if df.empty:
        return IndicatorSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            snapshot_time="",
            ema_20=None,
            ema_50=None,
            ema_200=None,
            price_vs_ema20_pct=None,
            price_vs_ema50_pct=None,
            price_vs_ema200_pct=None,
            vwap=None,
            price_vs_vwap_pct=None,
            rsi_14=None,
            atr_14=None,
            atr_14_pct=None,
            volume_ma_20=None,
            volume_current=None,
            trend_state=None,
            ema_alignment=None,
            vwap_state=None,
        )

    close = df["close"]
    price = float(close.iloc[-1])
    snapshot_time = pd.Timestamp(int(df["timestamp"].iloc[-1]), unit="ms", tz="UTC").isoformat()

    # ── EMAs ──────────────────────────────────────────────────────────────────
    ema20 = _safe_last(ta.ema(close, length=20))
    ema50 = _safe_last(ta.ema(close, length=50))
    ema200 = _safe_last(ta.ema(close, length=200))

    # ── VWAP (rolling) ────────────────────────────────────────────────────────
    vwap_series = _compute_rolling_vwap(df)
    vwap = _safe_last(vwap_series)

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_14 = _safe_last(ta.rsi(close, length=14))

    # ── ATR ───────────────────────────────────────────────────────────────────
    atr_series = ta.atr(df["high"], df["low"], close, length=14)
    atr_14 = _safe_last(atr_series)
    atr_14_pct = (atr_14 / price * 100.0) if atr_14 is not None and price > 0 else None

    # ── Volume ────────────────────────────────────────────────────────────────
    volume_ma_20 = _safe_last(ta.sma(df["volume"], length=20))
    volume_current = float(df["volume"].iloc[-1])

    # ── Price vs reference distances ──────────────────────────────────────────
    pve20 = _pct_diff(price, ema20)
    pve50 = _pct_diff(price, ema50)
    pve200 = _pct_diff(price, ema200)
    pvwap = _pct_diff(price, vwap)

    # ── Derived state classifications ──────────────────────────────────────────
    ts = _trend_state(price, ema20, ema50, ema200)
    ea = _ema_alignment(price, ema20, ema50, ema200)
    vs = _vwap_state(pvwap)

    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        snapshot_time=snapshot_time,
        ema_20=ema20,
        ema_50=ema50,
        ema_200=ema200,
        price_vs_ema20_pct=pve20,
        price_vs_ema50_pct=pve50,
        price_vs_ema200_pct=pve200,
        vwap=vwap,
        price_vs_vwap_pct=pvwap,
        rsi_14=rsi_14,
        atr_14=atr_14,
        atr_14_pct=atr_14_pct,
        volume_ma_20=volume_ma_20,
        volume_current=volume_current,
        trend_state=ts,
        ema_alignment=ea,
        vwap_state=vs,
    )


# ── Pipeline entry point ──────────────────────────────────────────────────────


def run_indicator_engine(bundles: list[AssetOHLCV]) -> IndicatorResult:
    """Compute all indicators for every asset in the fetcher output.

    For each AssetOHLCV, computes IndicatorSnapshot for 4h, 1h, and 30m.
    Failed assets (exceptions during computation) are logged and added to
    failed_symbols; all other assets continue through the pipeline.

    Args:
        bundles: list[AssetOHLCV] from fetch_market_data() (PR 5).

    Returns:
        IndicatorResult with successful AssetIndicators and failed_symbols.
    """
    if not bundles:
        log.warning("run_indicator_engine called with empty bundle list")
        return IndicatorResult()

    total = len(bundles)
    successful: list[AssetIndicators] = []
    failed_symbols: list[str] = []

    log.info("Stage 3 — computing indicators for %d assets (3 timeframes each)", total)

    for i, bundle in enumerate(bundles, start=1):
        try:
            tf4h = compute_indicators(bundle.symbol, "4h", bundle.candles_4h)
            tf1h = compute_indicators(bundle.symbol, "1h", bundle.candles_1h)
            tf30m = compute_indicators(bundle.symbol, "30m", bundle.candles_30m)

            asset_indicators = AssetIndicators(
                symbol=bundle.symbol,
                kraken_pair=bundle.kraken_pair,
                tf_4h=tf4h,
                tf_1h=tf1h,
                tf_30m=tf30m,
            )
            successful.append(asset_indicators)
            log.debug("[%d/%d] %s — indicators OK", i, total, bundle.symbol)

        except Exception as exc:
            log.warning(
                "[%d/%d] %s — indicator computation failed: %s", i, total, bundle.symbol, exc
            )
            failed_symbols.append(bundle.symbol)

    result = IndicatorResult(successful=successful, failed_symbols=failed_symbols)
    log.info(
        "Stage 3 complete — %d/%d computed (%.0f%%), %d failed%s",
        result.success_count,
        total,
        result.success_rate * 100,
        result.failure_count,
        f": {failed_symbols}" if failed_symbols else "",
    )
    return result
