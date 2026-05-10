"""Python dataclasses for the scanner pipeline.

These mirror the TypeScript contracts in packages/shared-types/src/scanner.ts.
Each PR adds the models it needs; future PRs extend this file.

PR 5 — Market Data Fetcher:
    OHLCVCandle, AssetOHLCV, FetchResult
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
