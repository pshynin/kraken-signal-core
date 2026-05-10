"""Python dataclasses for the scanner pipeline.

These mirror the TypeScript contracts in packages/shared-types/src/scanner.ts.
Each PR adds the models it needs; future PRs extend this file.

PR 5 — Market Data Fetcher:
    OHLCVCandle, AssetOHLCV, FetchResult

PR 6 — Indicator Engine:
    IndicatorSnapshot, AssetIndicators, IndicatorResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

# ── PR 5: Market Data Fetcher ─────────────────────────────────────────────────


class OHLCVCandle(NamedTuple):
    """Single OHLCV candlestick. Mirrors scanner.ts OHLCVCandle.

    timestamp — Unix milliseconds (ccxt convention)
    open/high/low/close — price in quote currency (USD)
    volume — base currency volume for this candle
    """

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class AssetOHLCV:
    """Multi-timeframe OHLCV bundle for one asset. Mirrors scanner.ts AssetOHLCV.

    Produced by the fetcher (PR 5) and consumed by the indicator engine (PR 6)
    and metric calculator (PR 7).

    symbol       — normalized ticker, e.g. "BTC"
    kraken_pair  — Kraken pair ID, e.g. "XXBTZUSD"
    candles_4h   — 4h candles (primary trend / structure timeframe)
    candles_1h   — 1h candles (momentum timeframe)
    candles_30m  — 30m candles (entry timing timeframe)
    fetched_at   — ISO 8601 timestamp of the fetch
    fetch_error  — non-None = partial failure on one or more timeframes
    """

    symbol: str
    kraken_pair: str
    candles_4h: list[OHLCVCandle]
    candles_1h: list[OHLCVCandle]
    candles_30m: list[OHLCVCandle]
    fetched_at: str
    fetch_error: str | None = None

    def candles_for(self, timeframe: str) -> list[OHLCVCandle]:
        """Return candles for the given timeframe string ('4h', '1h', '30m')."""
        mapping = {
            "4h": self.candles_4h,
            "1h": self.candles_1h,
            "30m": self.candles_30m,
        }
        if timeframe not in mapping:
            raise ValueError(f"Unknown timeframe: {timeframe!r}. Expected one of {list(mapping)}")
        return mapping[timeframe]

    @property
    def is_complete(self) -> bool:
        """True if all three timeframes have at least one candle and no errors."""
        return (
            self.fetch_error is None
            and len(self.candles_4h) > 0
            and len(self.candles_1h) > 0
            and len(self.candles_30m) > 0
        )


@dataclass
class FetchResult:
    """Output of fetch_market_data(). Carries successful bundles and failure list.

    successful    — AssetOHLCV list for assets that fetched without error
    failed_symbols — symbols that failed; these are excluded from the pipeline
    """

    successful: list[AssetOHLCV] = field(default_factory=list)
    failed_symbols: list[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed_symbols)

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Fraction of assets fetched successfully. 0.0 if universe was empty."""
        return self.success_count / self.total_count if self.total_count > 0 else 0.0


# ── PR 6: Indicator Engine ────────────────────────────────────────────────────

#: Literal values matching the indicator_snapshots DB CHECK constraints.
TREND_STATES = ("strong_up", "up", "neutral", "down", "strong_down")
EMA_ALIGNMENTS = ("bullish", "partial_bullish", "neutral", "bearish")
VWAP_STATES = ("above", "reclaiming", "below")


@dataclass
class IndicatorSnapshot:
    """Computed indicators for one asset on one timeframe.

    Mirrors scanner.ts IndicatorValues and maps 1:1 to indicator_snapshots columns.
    All price-derived fields are None when there are insufficient candles to compute.

    trend_state    — 'strong_up'|'up'|'neutral'|'down'|'strong_down'
    ema_alignment  — 'bullish'|'partial_bullish'|'neutral'|'bearish'
    vwap_state     — 'above'|'reclaiming'|'below'
    """

    symbol: str
    timeframe: str  # '4h' | '1h' | '30m'
    snapshot_time: str  # ISO 8601 timestamp of last closed candle

    ema_20: float | None
    ema_50: float | None
    ema_200: float | None
    price_vs_ema20_pct: float | None
    price_vs_ema50_pct: float | None
    price_vs_ema200_pct: float | None

    vwap: float | None
    price_vs_vwap_pct: float | None

    rsi_14: float | None

    atr_14: float | None
    atr_14_pct: float | None

    volume_ma_20: float | None
    volume_current: float | None

    trend_state: str | None
    ema_alignment: str | None
    vwap_state: str | None


@dataclass
class AssetIndicators:
    """Three-timeframe indicator bundle for one asset.

    Mirrors scanner.ts AssetIndicators.
    Produced by run_indicator_engine() and consumed by the hard filter (PR 7)
    and scoring engine (PR 8).
    """

    symbol: str
    kraken_pair: str
    tf_4h: IndicatorSnapshot
    tf_1h: IndicatorSnapshot
    tf_30m: IndicatorSnapshot

    def snapshot_for(self, timeframe: str) -> IndicatorSnapshot:
        """Return the IndicatorSnapshot for the given timeframe ('4h', '1h', '30m')."""
        mapping = {"4h": self.tf_4h, "1h": self.tf_1h, "30m": self.tf_30m}
        if timeframe not in mapping:
            raise ValueError(f"Unknown timeframe: {timeframe!r}")
        return mapping[timeframe]


@dataclass
class IndicatorResult:
    """Output of run_indicator_engine().

    successful    — AssetIndicators for assets that computed without error
    failed_symbols — symbols that raised exceptions (excluded downstream)
    """

    successful: list[AssetIndicators] = field(default_factory=list)
    failed_symbols: list[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed_symbols)

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_count if self.total_count > 0 else 0.0
