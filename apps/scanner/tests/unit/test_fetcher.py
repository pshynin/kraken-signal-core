"""Unit tests for scanner.fetcher and scanner.models — the market data layer.

All tests are fully offline: no ccxt, no HTTP, no Supabase.
fetch_fn is injected in every test that calls fetch_market_data / _fetch_asset_ohlcv.
"""

from __future__ import annotations

from typing import Any

import pytest

from scanner.fetcher import (
    _ccxt_symbol,
    _fetch_asset_ohlcv,
    _raw_to_candles,
    fetch_market_data,
)
from scanner.models import AssetOHLCV, FetchResult, OHLCVCandle
from scanner.universe import AssetUniverseItem

# ── Helpers ────────────────────────────────────────────────────────────────────

_BASE_TS_MS = 1_700_000_000_000  # arbitrary fixed start timestamp


def _make_raw_candles(n: int, timeframe: str = "4h", base_close: float = 100.0) -> list[list[Any]]:
    """Generate n synthetic ccxt-format OHLCV rows."""
    interval_ms = {"4h": 4 * 3600 * 1000, "1h": 3600 * 1000, "30m": 1800 * 1000}.get(
        timeframe, 3600 * 1000
    )
    rows: list[list[Any]] = []
    for i in range(n):
        close = base_close + i * 0.1
        row: list[Any] = [
            _BASE_TS_MS + i * interval_ms,
            close - 1,
            close + 1,
            close - 2,
            close,
            float(i + 1),
        ]
        rows.append(row)
    return rows


def _make_universe_item(symbol: str = "BTC", kraken_pair: str = "XXBTZUSD") -> AssetUniverseItem:
    return AssetUniverseItem(
        symbol=symbol,
        kraken_pair=kraken_pair,
        base_currency=symbol,
        quote_currency="USD",
        min_order_size=0.0001,
        lot_decimals=8,
        pair_decimals=1,
    )


def _make_mock_fetch_fn(n_candles: int = 10) -> Any:
    """Return a mock FetchFn that generates synthetic candles for any symbol/tf."""
    calls: list[tuple[str, str, int]] = []

    def mock_fetch(symbol: str, timeframe: str, limit: int) -> list[list[Any]]:
        calls.append((symbol, timeframe, limit))
        return _make_raw_candles(min(n_candles, limit), timeframe)

    mock_fetch.calls = calls  # type: ignore[attr-defined]
    return mock_fetch


# ── OHLCVCandle ───────────────────────────────────────────────────────────────


def test_ohlcv_candle_is_named_tuple() -> None:
    candle = OHLCVCandle(timestamp=1000, open=10.0, high=11.0, low=9.0, close=10.5, volume=50.0)
    assert candle.timestamp == 1000
    assert candle.close == 10.5


def test_ohlcv_candle_unpacking() -> None:
    candle = OHLCVCandle(1000, 10.0, 11.0, 9.0, 10.5, 50.0)
    ts, _o, h, _low, _c, _v = candle
    assert ts == 1000
    assert h == 11.0


# ── _raw_to_candles ───────────────────────────────────────────────────────────


def test_raw_to_candles_basic() -> None:
    raw = [[1_700_000_000_000, 60000.0, 61000.0, 59500.0, 60500.0, 100.5]]
    result = _raw_to_candles(raw)
    assert len(result) == 1
    c = result[0]
    assert isinstance(c, OHLCVCandle)
    assert c.timestamp == 1_700_000_000_000
    assert c.open == 60000.0
    assert c.high == 61000.0
    assert c.low == 59500.0
    assert c.close == 60500.0
    assert c.volume == 100.5


def test_raw_to_candles_multiple_rows() -> None:
    raw = _make_raw_candles(5)
    result = _raw_to_candles(raw)
    assert len(result) == 5
    assert all(isinstance(c, OHLCVCandle) for c in result)


def test_raw_to_candles_empty() -> None:
    assert _raw_to_candles([]) == []


def test_raw_to_candles_type_coercion() -> None:
    """Timestamps as str / floats from edge-case APIs should be coerced."""
    raw = [["1700000000000", "60000", "61000", "59500", "60500", "100"]]
    result = _raw_to_candles(raw)
    assert isinstance(result[0].timestamp, int)
    assert isinstance(result[0].open, float)


# ── _ccxt_symbol ──────────────────────────────────────────────────────────────


def test_ccxt_symbol_btc() -> None:
    item = _make_universe_item("BTC")
    assert _ccxt_symbol(item) == "BTC/USD"


def test_ccxt_symbol_sol() -> None:
    item = _make_universe_item("SOL", "SOLUSD")
    assert _ccxt_symbol(item) == "SOL/USD"


# ── _fetch_asset_ohlcv ────────────────────────────────────────────────────────


def test_fetch_asset_calls_all_timeframes() -> None:
    """fetch_fn must be called once per timeframe."""
    mock_fn = _make_mock_fetch_fn(10)
    item = _make_universe_item("SOL", "SOLUSD")

    _fetch_asset_ohlcv(item, mock_fn, timeframes=["4h", "1h", "30m"])

    called_tfs = [call[1] for call in mock_fn.calls]
    assert set(called_tfs) == {"4h", "1h", "30m"}
    assert len(mock_fn.calls) == 3


def test_fetch_asset_candles_in_correct_fields() -> None:
    """Candles returned for each timeframe must land in the right field."""
    mock_fn = _make_mock_fetch_fn(5)
    item = _make_universe_item()

    result = _fetch_asset_ohlcv(item, mock_fn)

    assert len(result.candles_4h) == 5
    assert len(result.candles_1h) == 5
    assert len(result.candles_30m) == 5


def test_fetch_asset_limit_forwarded_to_fetch_fn() -> None:
    """The limit parameter must be passed through to fetch_fn."""
    mock_fn = _make_mock_fetch_fn(250)
    item = _make_universe_item()

    _fetch_asset_ohlcv(item, mock_fn, limit=137)

    assert all(call[2] == 137 for call in mock_fn.calls)


def test_fetch_asset_fields_populated() -> None:
    mock_fn = _make_mock_fetch_fn(10)
    item = _make_universe_item("ETH", "XETHZUSD")

    result = _fetch_asset_ohlcv(item, mock_fn)

    assert result.symbol == "ETH"
    assert result.kraken_pair == "XETHZUSD"
    assert result.fetch_error is None
    assert result.fetched_at  # non-empty ISO string


def test_fetch_asset_is_complete() -> None:
    mock_fn = _make_mock_fetch_fn(10)
    result = _fetch_asset_ohlcv(_make_universe_item(), mock_fn)
    assert result.is_complete is True


def test_fetch_asset_candles_for_helper() -> None:
    mock_fn = _make_mock_fetch_fn(7)
    result = _fetch_asset_ohlcv(_make_universe_item(), mock_fn)
    assert result.candles_for("4h") is result.candles_4h
    assert result.candles_for("1h") is result.candles_1h
    assert result.candles_for("30m") is result.candles_30m


# ── fetch_market_data ─────────────────────────────────────────────────────────


def test_fetch_market_data_all_success() -> None:
    universe = [
        _make_universe_item("BTC", "XXBTZUSD"),
        _make_universe_item("SOL", "SOLUSD"),
        _make_universe_item("ETH", "XETHZUSD"),
    ]
    result = fetch_market_data(universe, fetch_fn=_make_mock_fetch_fn(10))

    assert result.success_count == 3
    assert result.failure_count == 0
    assert result.failed_symbols == []
    symbols = [a.symbol for a in result.successful]
    assert "BTC" in symbols and "SOL" in symbols and "ETH" in symbols


def test_fetch_market_data_partial_failure() -> None:
    """When one asset fails, it lands in failed_symbols; others succeed."""

    def flaky_fetch(symbol: str, timeframe: str, limit: int) -> list[list[Any]]:
        if "ETH" in symbol:
            raise RuntimeError("Simulated network error for ETH")
        return _make_raw_candles(10, timeframe)

    universe = [
        _make_universe_item("BTC", "XXBTZUSD"),
        _make_universe_item("ETH", "XETHZUSD"),
        _make_universe_item("SOL", "SOLUSD"),
    ]
    result = fetch_market_data(universe, fetch_fn=flaky_fetch)

    assert result.success_count == 2
    assert result.failure_count == 1
    assert "ETH" in result.failed_symbols
    assert result.success_rate == pytest.approx(2 / 3)


def test_fetch_market_data_all_fail() -> None:
    def always_fail(symbol: str, timeframe: str, limit: int) -> list[list[Any]]:
        raise ConnectionError("Exchange unavailable")

    universe = [_make_universe_item("BTC"), _make_universe_item("SOL")]
    result = fetch_market_data(universe, fetch_fn=always_fail)

    assert result.success_count == 0
    assert result.failure_count == 2
    assert result.success_rate == 0.0


def test_fetch_market_data_empty_universe() -> None:
    result = fetch_market_data([], fetch_fn=_make_mock_fetch_fn())
    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.success_rate == 0.0


# ── FetchResult properties ────────────────────────────────────────────────────


def test_fetch_result_success_rate_full() -> None:
    r = FetchResult(successful=[_make_asset_ohlcv("BTC"), _make_asset_ohlcv("SOL")])
    assert r.success_rate == 1.0


def test_fetch_result_success_rate_partial() -> None:
    r = FetchResult(successful=[_make_asset_ohlcv("BTC")], failed_symbols=["SOL"])
    assert r.success_rate == pytest.approx(0.5)


def test_fetch_result_success_rate_zero_total() -> None:
    r = FetchResult()
    assert r.success_rate == 0.0


def test_fetch_result_counts() -> None:
    r = FetchResult(
        successful=[_make_asset_ohlcv("BTC"), _make_asset_ohlcv("ETH")],
        failed_symbols=["SOL", "AVAX"],
    )
    assert r.total_count == 4
    assert r.success_count == 2
    assert r.failure_count == 2


# ── AssetOHLCV helpers ────────────────────────────────────────────────────────


def test_asset_ohlcv_is_complete_false_when_empty_timeframe() -> None:
    asset = AssetOHLCV(
        symbol="BTC",
        kraken_pair="XXBTZUSD",
        candles_4h=[],
        candles_1h=[OHLCVCandle(1000, 1.0, 1.0, 1.0, 1.0, 1.0)],
        candles_30m=[OHLCVCandle(1000, 1.0, 1.0, 1.0, 1.0, 1.0)],
        fetched_at="2026-01-01T00:00:00Z",
    )
    assert asset.is_complete is False


def test_asset_ohlcv_is_complete_false_with_error() -> None:
    candles = [OHLCVCandle(1000, 1.0, 1.0, 1.0, 1.0, 1.0)]
    asset = AssetOHLCV(
        symbol="BTC",
        kraken_pair="XXBTZUSD",
        candles_4h=candles,
        candles_1h=candles,
        candles_30m=candles,
        fetched_at="2026-01-01T00:00:00Z",
        fetch_error="partial timeout on 30m",
    )
    assert asset.is_complete is False


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_asset_ohlcv(symbol: str) -> AssetOHLCV:
    candle = OHLCVCandle(1000, 1.0, 1.0, 1.0, 1.0, 1.0)
    return AssetOHLCV(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        candles_4h=[candle],
        candles_1h=[candle],
        candles_30m=[candle],
        fetched_at="2026-01-01T00:00:00Z",
    )
