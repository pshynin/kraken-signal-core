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


# ── PR 7: Hard Filter + Market Metrics ───────────────────────────────────────


@dataclass
class MarketMetrics:
    """Computed market metrics for one asset. Maps 1:1 to market_snapshots columns.

    Produced by compute_market_metrics() (PR 7) from 4h OHLCV candles.
    Consumed by run_hard_filter() (PR 7) and the scoring engine (PR 8).

    Returns are fractional, e.g. 0.08 = +8%.
    Distances are fractional and negative when price is below the reference high.
    """

    symbol: str
    kraken_pair: str
    snapshot_time: str  # ISO 8601 timestamp of last closed 4h candle

    price_usd: float
    price_btc: float | None  # future: price_usd / btc_price; None until PR 10

    volume_24h_usd: float | None
    volume_7d_avg_usd: float | None
    volume_ratio_20d: float | None  # volume_24h / 20-day avg daily volume

    return_3d: float | None
    return_7d: float | None
    return_14d: float | None
    return_vs_btc_7d: float | None  # return_7d minus BTC 7d return

    dist_from_7d_high: float | None  # (close - 7d_high) / 7d_high, always <= 0
    dist_from_20d_high: float | None

    spread_pct: float | None  # OHLC-proxy: mean (high-low)/close over last 6 candles
    atr_pct_7d: float | None  # reused from AssetIndicators.tf_4h.atr_14_pct


@dataclass
class HardFilterResult:
    """Outcome of the hard filter for one asset.

    passed=True  — asset clears all rules; proceeds to the scoring engine.
    passed=False — exclusion_reason holds the first failing rule name.
    """

    symbol: str
    passed: bool
    exclusion_reason: str | None  # None iff passed is True


@dataclass
class FilterResult:
    """Output of run_hard_filter().

    passed_metrics    — MarketMetrics for assets clearing all hard rules.
    passed_indicators — AssetIndicators in the same order (co-indexed with passed_metrics).
    exclusions        — HardFilterResult for every rejected asset.
    """

    passed_metrics: list[MarketMetrics] = field(default_factory=list)
    passed_indicators: list[AssetIndicators] = field(default_factory=list)
    exclusions: list[HardFilterResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return len(self.passed_metrics)

    @property
    def excluded_count(self) -> int:
        return len(self.exclusions)

    @property
    def total_count(self) -> int:
        return self.passed_count + self.excluded_count

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.total_count if self.total_count > 0 else 0.0


# ── PR 8: Scoring Engine ──────────────────────────────────────────────────────


@dataclass
class ScoreBreakdown:
    """9-factor scoring result for one asset. Maps 1:1 to candidate_scores columns.

    Produced by score_asset() (PR 8). Consumed by the candidate selector (PR 9)
    and persisted to candidate_scores by the run persister (PR 10).

    All sub-scores are non-negative floats at or below their stated maximums.
    score_total == sum of all nine components, capped at 100.

    category:
        'clean'     — score >= 70 + clean-specific thresholds (volume, RSI, anti-chase)
        'ugly'      — score >= 62 + ugly-specific thresholds
        'watchlist' — score >= 55, just misses clean/ugly qualification
        'excluded'  — used by the DB persister for hard-filtered assets (not from scorer)
    """

    symbol: str
    category: str | None  # 'clean' | 'ugly' | 'watchlist' | 'excluded' | None
    exclusion_reason: str | None  # None for scored assets; populated from HardFilterResult

    score_total: float  # 0–100
    score_liquidity: float  # /20  — volume & tradability
    score_upside: float  # /15  — 7-10 day upside feasibility
    score_volatility: float  # /10  — ATR expansion / sweet spot
    score_structure: float  # /15  — multi-TF EMA + VWAP structure
    score_rel_strength: float  # /10  — relative performance vs BTC
    score_volume: float  # /10  — volume confirmation
    score_catalyst: float  # /10  — catalyst / market attention proxy
    score_supply_risk: float  # /5   — overhead supply risk
    score_execution: float  # /5   — entry zone clarity

    probability_pct: float | None  # heuristic success percentile (not a guarantee)


@dataclass
class ScoringResult:
    """Output of run_scoring_engine().

    scores — ScoreBreakdown for every asset that passed the hard filter,
             sorted by score_total descending.
    """

    scores: list[ScoreBreakdown] = field(default_factory=list)

    @property
    def clean(self) -> list[ScoreBreakdown]:
        return [s for s in self.scores if s.category == "clean"]

    @property
    def ugly(self) -> list[ScoreBreakdown]:
        return [s for s in self.scores if s.category == "ugly"]

    @property
    def watchlist(self) -> list[ScoreBreakdown]:
        return [s for s in self.scores if s.category == "watchlist"]

    @property
    def clean_count(self) -> int:
        return len(self.clean)

    @property
    def ugly_count(self) -> int:
        return len(self.ugly)


# ── PR 9: Candidate Selector + Trade Parameters ───────────────────────────────

# Valid size bucket values — must match crecs_size_bucket_check DB constraint.
SIZE_BUCKETS: tuple[str, ...] = ("2k", "2k-5k", "5k-10k", "10k-20k", "20k+")


@dataclass
class TradeParameters:
    """Computed entry/exit/stop/size parameters for one candidate.

    Maps 1:1 to candidate_recommendations trade columns.

    DB constraints enforced at construction time in selector.py:
        stop_loss < entry_price
        exit_price > entry_price
        entry_price_low <= entry_price_high (when both present)

    expected_gain_pct is expressed as a percentage (10.0 = +10%), matching the
    migration 0007 NUMERIC(8,4) column definition and the comment:
    "(exit − entry_midpoint) / entry_midpoint × 100".
    reward_risk_ratio is a pure ratio (2.5 = 2.5× reward per unit of risk).
    """

    symbol: str

    entry_price: float  # midpoint of entry zone
    entry_price_low: float | None  # lower bound (limit order floor)
    entry_price_high: float | None  # upper bound (breakout trigger)
    exit_price: float  # target / sell order price
    stop_loss: float  # stop loss price

    suggested_size_bucket: str  # '2k' | '2k-5k' | '5k-10k' | '10k-20k' | '20k+'
    expected_gain_pct: float  # (exit - entry) / entry × 100
    reward_risk_ratio: float  # (exit - entry) / (entry - stop_loss)
    notes: str | None  # scanner-generated rationale for Discord / dashboard

    current_price: float  # spot price at scan time; entry_price must be strictly below this
    distance_to_entry_pct: float  # (entry_price − current_price) / current_price × 100; always < 0


@dataclass
class ScoredCandidate:
    """A ranked, fully parameterised trade candidate.

    Aggregates all four per-asset outputs from the scanner pipeline
    (score, trade parameters, market metrics, indicators) into one object
    ready for DB persistence (PR 10) and Discord alerting (PR 11).
    """

    symbol: str
    kraken_pair: str
    category: str  # 'clean' | 'ugly'
    rank: int  # 1 = best in category

    score: ScoreBreakdown
    trade: TradeParameters
    market: MarketMetrics
    indicators: AssetIndicators


@dataclass
class SelectionResult:
    """Output of run_candidate_selector().

    clean — top-N clean candidates sorted by score_total descending (rank 1 = best).
    ugly  — top-N ugly candidates sorted by score_total descending.
    """

    clean: list[ScoredCandidate] = field(default_factory=list)
    ugly: list[ScoredCandidate] = field(default_factory=list)

    @property
    def all_candidates(self) -> list[ScoredCandidate]:
        return self.clean + self.ugly

    @property
    def total_count(self) -> int:
        return len(self.clean) + len(self.ugly)
