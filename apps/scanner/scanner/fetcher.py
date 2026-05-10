"""Market Data Fetcher — PR 5.

Fetches OHLCV candle data for every asset in the universe across the three
analysis timeframes (4h / 1h / 30m) using the ccxt Kraken exchange client.

Public API:
    fetch_market_data(
        universe:  list[AssetUniverseItem],
        fetch_fn:  FetchFn | None = None,   # injectable for tests
    ) -> FetchResult

Design:
    - ccxt.kraken with enableRateLimit=True handles automatic throttling.
    - fetch_fn is injectable: pass a mock in tests to avoid real HTTP calls.
      If fetch_fn is None (production), a live ccxt client is created and
      load_markets() is called once before the fetch loop.
    - Failed assets are logged and collected in FetchResult.failed_symbols.
      They are excluded from all subsequent pipeline stages. The run
      continues with the remaining assets.
    - Candles fetched per timeframe: CANDLES_PER_TIMEFRAME (default 250).
      EMA 200 requires 200+ candles; 250 gives a 50-candle convergence buffer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import ccxt

from scanner.models import AssetOHLCV, FetchResult, OHLCVCandle
from scanner.universe import AssetUniverseItem

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CANDLES_PER_TIMEFRAME: int = 250
"""Number of candles fetched per timeframe.
EMA 200 needs 200 closed candles. +50 buffer for indicator convergence."""

TIMEFRAMES: list[str] = ["4h", "1h", "30m"]
"""Timeframes fetched for each asset. Order determines the ccxt call sequence."""

KRAKEN_RATE_LIMIT_MS: int = 500
"""Milliseconds between ccxt requests. 500ms = 2 req/s — conservative for
Kraken's public API to avoid 429s across a full universe scan."""

# ── Types ──────────────────────────────────────────────────────────────────────

FetchFn = Callable[[str, str, int], list[list[Any]]]
"""Callable signature: (ccxt_symbol, timeframe, limit) → raw ccxt OHLCV rows.
Each row: [timestamp_ms, open, high, low, close, volume]."""


# ── Exchange factory ──────────────────────────────────────────────────────────


def create_exchange() -> ccxt.kraken:
    """Create and return a rate-limited Kraken ccxt exchange instance."""
    return ccxt.kraken(
        {
            "enableRateLimit": True,
            "rateLimit": KRAKEN_RATE_LIMIT_MS,
        }
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _ccxt_symbol(item: AssetUniverseItem, pair_id_map: dict[str, str] | None = None) -> str:
    """Return the ccxt market symbol for an asset.

    Prefers a lookup in pair_id_map (kraken_pair → ccxt_symbol) built from
    exchange.markets after load_markets(), which handles rebranded or
    non-standard pairs like LUNA2/USD correctly.

    Falls back to constructing 'SYMBOL/USD' if the pair ID is not in the map.
    """
    if pair_id_map and item.kraken_pair in pair_id_map:
        return pair_id_map[item.kraken_pair]
    return f"{item.symbol}/{item.quote_currency}"


def _raw_to_candles(raw: list[list[Any]]) -> list[OHLCVCandle]:
    """Convert raw ccxt OHLCV rows to OHLCVCandle NamedTuples.

    ccxt row format: [timestamp_ms, open, high, low, close, volume]
    """
    return [
        OHLCVCandle(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in raw
    ]


def _fetch_asset_ohlcv(
    item: AssetUniverseItem,
    fetch_fn: FetchFn,
    timeframes: list[str] = TIMEFRAMES,
    limit: int = CANDLES_PER_TIMEFRAME,
    ccxt_symbol_override: str | None = None,
) -> AssetOHLCV:
    """Fetch OHLCV candles for all timeframes for one asset.

    Args:
        item:                 Asset to fetch.
        fetch_fn:             Callable(symbol, timeframe, limit) → raw rows.
        timeframes:           Timeframes to fetch (default: TIMEFRAMES).
        limit:                Candles per timeframe (default: CANDLES_PER_TIMEFRAME).
        ccxt_symbol_override: Use this ccxt symbol instead of constructing from
                              item.symbol. Allows correct mapping for rebranded
                              pairs (e.g. LUNA → LUNA2/USD).

    Returns:
        AssetOHLCV with all timeframe candle lists populated.

    Raises:
        Exception: propagated from fetch_fn if any timeframe fetch fails.
                   Caller is responsible for catching and recording failures.
    """
    ccxt_sym = ccxt_symbol_override if ccxt_symbol_override else _ccxt_symbol(item)
    fetched_at = datetime.now(UTC).isoformat()
    candles: dict[str, list[OHLCVCandle]] = {}

    for tf in timeframes:
        raw = fetch_fn(ccxt_sym, tf, limit)
        candles[tf] = _raw_to_candles(raw)
        log.debug("%s [%s]: %d candles", item.symbol, tf, len(candles[tf]))

    return AssetOHLCV(
        symbol=item.symbol,
        kraken_pair=item.kraken_pair,
        candles_4h=candles.get("4h", []),
        candles_1h=candles.get("1h", []),
        candles_30m=candles.get("30m", []),
        fetched_at=fetched_at,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def fetch_market_data(
    universe: list[AssetUniverseItem],
    fetch_fn: FetchFn | None = None,
) -> FetchResult:
    """Fetch OHLCV data for all assets in the universe.

    Args:
        universe:  List of AssetUniverseItem from the universe loader (PR 4).
        fetch_fn:  Callable(ccxt_symbol, timeframe, limit) → raw OHLCV rows.
                   If None (production), a live ccxt.kraken client is created.
                   Override with a mock in tests to avoid real HTTP.

    Returns:
        FetchResult:
            - successful:     list of AssetOHLCV for assets that fetched cleanly
            - failed_symbols: symbols that raised exceptions (excluded downstream)
    """
    if not universe:
        log.warning("fetch_market_data called with empty universe")
        return FetchResult()

    if fetch_fn is None:
        exchange = create_exchange()
        log.info("Loading Kraken markets via ccxt")
        exchange.load_markets()

        # Build reverse map: kraken pair ID → ccxt symbol
        # e.g. {"XXBTZUSD": "BTC/USD", "LUNAUSD": "LUNA2/USD", ...}
        pair_id_map: dict[str, str] = {
            market["id"]: ccxt_sym for ccxt_sym, market in exchange.markets.items()
        }
        log.debug("ccxt pair_id_map built: %d entries", len(pair_id_map))

        def _live(sym: str, tf: str, lim: int) -> list[list[Any]]:
            return cast(list[list[Any]], exchange.fetch_ohlcv(sym, tf, limit=lim))

        fetch_fn = _live
    else:
        pair_id_map = {}

    total = len(universe)
    successful: list[AssetOHLCV] = []
    failed_symbols: list[str] = []

    log.info("Stage 2 — fetching OHLCV for %d assets (%d timeframes each)", total, len(TIMEFRAMES))

    for i, item in enumerate(universe, start=1):
        try:
            result = _fetch_asset_ohlcv(
                item,
                fetch_fn,
                ccxt_symbol_override=_ccxt_symbol(item, pair_id_map),
            )
            successful.append(result)
            log.debug(
                "[%d/%d] %s — OK (%d×%d candles)",
                i,
                total,
                item.symbol,
                len(TIMEFRAMES),
                CANDLES_PER_TIMEFRAME,
            )
        except Exception as exc:
            log.warning("[%d/%d] %s — fetch failed: %s", i, total, item.symbol, exc)
            failed_symbols.append(item.symbol)

    fetch_result = FetchResult(successful=successful, failed_symbols=failed_symbols)
    log.info(
        "Stage 2 complete — %d/%d fetched (%.0f%%), %d failed%s",
        fetch_result.success_count,
        total,
        fetch_result.success_rate * 100,
        fetch_result.failure_count,
        f": {failed_symbols}" if failed_symbols else "",
    )
    return fetch_result
