"""Kraken Universe Loader — PR 4.

Loads and filters the full Kraken tradable spot universe.

Public API:
    load_universe(fetch_fn=fetch_asset_pairs) -> list[AssetUniverseItem]

Design:
    - fetch_asset_pairs()  — HTTP only, injectable for tests
    - parse_universe()     — pure function, no I/O, fully testable without mocking
    - load_universe()      — composes the above; accepts custom fetch_fn for DI

Filter rules (applied in order):
    1. Pair ID must not end with ".d"  (dark pool / institutional OTC)
    2. quote must be "ZUSD"            (USD spot pairs only)
    3. status must be "online"         (active listing only)
    4. wsname must be present          (malformed pair guard)
    5. Normalized base must not be in  STABLECOIN_BASES (no stable/USD noise)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

KRAKEN_API_BASE = "https://api.kraken.com"
ASSET_PAIRS_ENDPOINT = "/0/public/AssetPairs"
REQUEST_TIMEOUT_SECONDS = 30.0

# Kraken uses non-standard symbols for some assets; normalize to common tickers.
SYMBOL_NORMALIZATIONS: dict[str, str] = {
    "XBT": "BTC",  # Kraken calls Bitcoin "XBT"
    "XDG": "DOGE",  # Kraken calls Dogecoin "XDG" on some pairs
}

# Base currencies that are stablecoins — filter out stable/USD pairs since they
# have no momentum signal and pollute the universe.
STABLECOIN_BASES: frozenset[str] = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "DAI",
        "TUSD",
        "USDP",
        "USDD",
        "FDUSD",
        "PYUSD",
        "AEUR",
        "EURT",
        "EURS",
        "XCHF",
    }
)


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetUniverseItem:
    """One tradable USD spot asset from the Kraken universe.

    symbol       — normalized common ticker, e.g. "BTC", "SOL", "ETH"
    kraken_pair  — raw Kraken pair ID, e.g. "XXBTZUSD", "SOLUSD"
    base_currency — normalized base (same as symbol for most assets)
    quote_currency — always "USD" after filtering
    min_order_size — Kraken's ordermin field (float)
    lot_decimals   — precision for order quantity
    pair_decimals  — precision for order price
    """

    symbol: str
    kraken_pair: str
    base_currency: str
    quote_currency: str
    min_order_size: float
    lot_decimals: int
    pair_decimals: int


# ── Filter logic ──────────────────────────────────────────────────────────────


def _normalize_symbol(raw: str) -> str:
    """Apply Kraken-specific symbol normalizations (e.g. XBT → BTC)."""
    return SYMBOL_NORMALIZATIONS.get(raw, raw)


def _is_tradable_usd_spot(pair_id: str, pair_data: dict[str, Any]) -> bool:
    """Return True if this pair belongs in the scanner universe.

    Pure predicate — no side effects, easy to unit test.
    """
    # 1. Dark pool / OTC — Kraken appends ".d" suffix
    if pair_id.endswith(".d"):
        return False

    # 2. USD spot only — Kraken uses "ZUSD" internally for USD
    if pair_data.get("quote") != "ZUSD":
        return False

    # 3. Active listing only
    if pair_data.get("status") != "online":
        return False

    # 4. Must have a websocket name (guard against malformed entries)
    wsname: str | None = pair_data.get("wsname")
    if not wsname:
        return False

    # 5. Exclude stablecoin/USD pairs (no momentum signal)
    base_raw = wsname.split("/")[0]
    normalized_base = _normalize_symbol(base_raw)
    if normalized_base in STABLECOIN_BASES:
        return False

    return True


# ── HTTP layer ────────────────────────────────────────────────────────────────


def fetch_asset_pairs() -> dict[str, Any]:
    """Fetch raw AssetPairs result from the Kraken public REST API.

    Returns:
        The "result" dict from the API response (keyed by pair ID).

    Raises:
        httpx.HTTPError: on network or HTTP-level failures.
        RuntimeError: if Kraken returns an API-level error.
    """
    url = f"{KRAKEN_API_BASE}{ASSET_PAIRS_ENDPOINT}"
    log.info("Fetching Kraken AssetPairs from %s", url)

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(url)
        response.raise_for_status()

    data: dict[str, Any] = response.json()

    if errors := data.get("error"):
        raise RuntimeError(f"Kraken API returned errors: {errors}")

    result: dict[str, Any] = data.get("result", {})
    log.debug("Kraken AssetPairs: %d total pairs received", len(result))
    return result


# ── Parse layer ───────────────────────────────────────────────────────────────


def parse_universe(pairs: dict[str, Any]) -> list[AssetUniverseItem]:
    """Filter and normalize raw AssetPairs data into a sorted universe list.

    Pure function — no I/O. Accepts raw Kraken AssetPairs result dict.

    Returns:
        List of AssetUniverseItem, sorted alphabetically by symbol.
    """
    universe: list[AssetUniverseItem] = []
    excluded_count = 0

    for pair_id, pair_data in pairs.items():
        if not _is_tradable_usd_spot(pair_id, pair_data):
            excluded_count += 1
            continue

        wsname: str = pair_data["wsname"]
        base_raw = wsname.split("/")[0]
        base_normalized = _normalize_symbol(base_raw)

        item = AssetUniverseItem(
            symbol=base_normalized,
            kraken_pair=pair_id,
            base_currency=base_normalized,
            quote_currency="USD",
            min_order_size=float(pair_data.get("ordermin", 0)),
            lot_decimals=int(pair_data.get("lot_decimals", 8)),
            pair_decimals=int(pair_data.get("pair_decimals", 2)),
        )
        universe.append(item)

    universe.sort(key=lambda x: x.symbol)

    log.info(
        "Universe parsed: %d tradable USD spot pairs, %d excluded",
        len(universe),
        excluded_count,
    )
    return universe


# ── Public API ────────────────────────────────────────────────────────────────

FetchFn = Callable[[], dict[str, Any]]


def load_universe(fetch_fn: FetchFn = fetch_asset_pairs) -> list[AssetUniverseItem]:
    """Load and return the full tradable Kraken USD spot universe.

    Args:
        fetch_fn: Callable that returns the raw AssetPairs dict.
                  Defaults to fetch_asset_pairs() (live API).
                  Override in tests to avoid real HTTP calls.

    Returns:
        Sorted list of AssetUniverseItem.
    """
    pairs = fetch_fn()
    return parse_universe(pairs)
