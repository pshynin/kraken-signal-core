"""Unit tests for scanner.universe — the Kraken universe loader.

Tests are fully offline: no HTTP calls, no Supabase.
The fixture in tests/fixtures/kraken_asset_pairs.json contains 9 pairs:
  - 4 valid USD spot pairs (AVAX, BTC, ETH, SOL)
  - 5 excluded (dark pool, USDT quote, EUR quote, stablecoin, offline)
"""

from __future__ import annotations

import json
from pathlib import Path

from scanner.universe import (
    STABLECOIN_BASES,
    AssetUniverseItem,
    _is_tradable_usd_spot,
    _normalize_symbol,
    load_universe,
    parse_universe,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture() -> dict:
    """Load the Kraken AssetPairs fixture (result field format)."""
    path = FIXTURES_DIR / "kraken_asset_pairs.json"
    with path.open() as f:
        return json.load(f)


# ── Symbol normalization ──────────────────────────────────────────────────────


def test_normalize_symbol_xbt_to_btc() -> None:
    assert _normalize_symbol("XBT") == "BTC"


def test_normalize_symbol_xdg_to_doge() -> None:
    assert _normalize_symbol("XDG") == "DOGE"


def test_normalize_symbol_passthrough() -> None:
    """Symbols with no normalization rule are returned unchanged."""
    assert _normalize_symbol("SOL") == "SOL"
    assert _normalize_symbol("ETH") == "ETH"
    assert _normalize_symbol("AVAX") == "AVAX"


# ── _is_tradable_usd_spot predicate ──────────────────────────────────────────


def test_filter_rejects_dark_pool() -> None:
    pair_data = {
        "wsname": "XBT/USD",
        "quote": "ZUSD",
        "status": "online",
    }
    assert _is_tradable_usd_spot("XXBTZUSD.d", pair_data) is False


def test_filter_rejects_non_zusd_quote() -> None:
    """USDT quote pairs are not USD — must be excluded."""
    pair_data = {
        "wsname": "SOL/USDT",
        "quote": "USDT",
        "status": "online",
    }
    assert _is_tradable_usd_spot("SOLUSDT", pair_data) is False


def test_filter_rejects_eur_quote() -> None:
    pair_data = {
        "wsname": "XBT/EUR",
        "quote": "ZEUR",
        "status": "online",
    }
    assert _is_tradable_usd_spot("XXBTZEUR", pair_data) is False


def test_filter_rejects_offline_pair() -> None:
    pair_data = {
        "wsname": "LTC/USD",
        "quote": "ZUSD",
        "status": "offline",
    }
    assert _is_tradable_usd_spot("LTCUSD", pair_data) is False


def test_filter_rejects_stablecoin_base() -> None:
    pair_data = {
        "wsname": "USDT/USD",
        "quote": "ZUSD",
        "status": "online",
    }
    assert _is_tradable_usd_spot("USDTZUSD", pair_data) is False


def test_filter_rejects_missing_wsname() -> None:
    pair_data = {
        "quote": "ZUSD",
        "status": "online",
    }
    assert _is_tradable_usd_spot("SOMEUSD", pair_data) is False


def test_filter_accepts_valid_pair() -> None:
    pair_data = {
        "wsname": "SOL/USD",
        "quote": "ZUSD",
        "status": "online",
    }
    assert _is_tradable_usd_spot("SOLUSD", pair_data) is True


# ── parse_universe ────────────────────────────────────────────────────────────


def test_parse_universe_count() -> None:
    """Fixture has 4 valid pairs (AVAX, BTC, ETH, SOL)."""
    pairs = load_fixture()
    result = parse_universe(pairs)
    assert len(result) == 4


def test_parse_universe_symbols() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    symbols = [item.symbol for item in result]
    assert "BTC" in symbols  # XBT → BTC normalization
    assert "ETH" in symbols
    assert "SOL" in symbols
    assert "AVAX" in symbols


def test_parse_universe_sorted_alphabetically() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    symbols = [item.symbol for item in result]
    assert symbols == sorted(symbols), f"Expected sorted, got: {symbols}"


def test_parse_universe_xbt_normalized_to_btc() -> None:
    """The XBT/USD pair should become symbol='BTC', not 'XBT'."""
    pairs = load_fixture()
    result = parse_universe(pairs)
    btc = next(item for item in result if item.symbol == "BTC")
    assert btc.kraken_pair == "XXBTZUSD"
    assert btc.base_currency == "BTC"
    assert btc.quote_currency == "USD"


def test_parse_universe_fields_populated() -> None:
    """Verify all expected fields are set on a known pair."""
    pairs = load_fixture()
    result = parse_universe(pairs)
    sol = next(item for item in result if item.symbol == "SOL")

    assert sol.kraken_pair == "SOLUSD"
    assert sol.base_currency == "SOL"
    assert sol.quote_currency == "USD"
    assert sol.min_order_size == 0.5
    assert sol.lot_decimals == 8
    assert sol.pair_decimals == 2


def test_parse_universe_excludes_dark_pool() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    kraken_pairs = {item.kraken_pair for item in result}
    assert "XXBTZUSD.d" not in kraken_pairs


def test_parse_universe_excludes_stablecoin() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    symbols = {item.symbol for item in result}
    assert "USDT" not in symbols


def test_parse_universe_excludes_offline() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    kraken_pairs = {item.kraken_pair for item in result}
    assert "LTCUSD" not in kraken_pairs


def test_parse_universe_returns_dataclasses() -> None:
    pairs = load_fixture()
    result = parse_universe(pairs)
    assert all(isinstance(item, AssetUniverseItem) for item in result)


# ── load_universe dependency injection ───────────────────────────────────────


def test_load_universe_uses_injected_fetch_fn() -> None:
    """load_universe should call the provided fetch_fn instead of live API."""
    fixture = load_fixture()
    called_with: list[bool] = []

    def mock_fetch() -> dict:
        called_with.append(True)
        return fixture

    result = load_universe(fetch_fn=mock_fetch)

    assert called_with == [True], "fetch_fn was not called"
    assert len(result) == 4
    assert result[0].symbol == "AVAX"  # alphabetically first


# ── STABLECOIN_BASES completeness ─────────────────────────────────────────────


def test_stablecoin_bases_includes_major_stables() -> None:
    """Sanity check that the most common stablecoins are in the exclusion set."""
    for symbol in ("USDT", "USDC", "DAI", "BUSD"):
        assert symbol in STABLECOIN_BASES, f"{symbol} missing from STABLECOIN_BASES"
