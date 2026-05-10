"""Supabase client factory and database write operations.

All DB writes go through this module — keeps scanner pipeline stages
free of Supabase SDK details and easy to mock in tests.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from supabase import Client, create_client

from scanner.config import ScannerConfig
from scanner.universe import AssetUniverseItem

log = logging.getLogger(__name__)


def get_client(config: ScannerConfig) -> Client:
    """Create and return a Supabase service-role client."""
    return create_client(config.supabase_url, config.supabase_service_role_key)


def upsert_assets(client: Client, items: list[AssetUniverseItem]) -> int:
    """Upsert universe assets into the assets table.

    Conflict key: kraken_pair (unique in the DB).
    On conflict: updates symbol, base_currency, is_active, last_seen_at.
    Intentionally does NOT update excluded_reason — a manually excluded asset
    keeps its exclusion across scans.

    Returns:
        Number of rows upserted.
    """
    if not items:
        log.warning("upsert_assets called with empty list — nothing to write")
        return 0

    now_iso = datetime.now(UTC).isoformat()

    rows: list[dict[str, Any]] = [
        {
            "symbol": item.symbol,
            "kraken_pair": item.kraken_pair,
            "base_currency": item.base_currency,
            "quote_currency": item.quote_currency,
            "is_active": True,
            "last_seen_at": now_iso,
            # created_at / updated_at — handled by DB defaults + trigger
            # excluded_reason — intentionally omitted; not overwritten on conflict
        }
        for item in items
    ]

    response = client.table("assets").upsert(rows, on_conflict="kraken_pair").execute()

    count = len(response.data) if response.data else 0
    log.info("upsert_assets: %d rows written to assets table", count)
    return count


def mark_stale_assets_inactive(client: Client, active_kraken_pairs: list[str]) -> int:
    """Set is_active = False for any asset not present in the current universe.

    Called after upsert_assets so the DB reflects Kraken's current listing state.
    Assets that were delisted or paused will be marked inactive.

    Returns:
        Number of rows updated.
    """
    if not active_kraken_pairs:
        return 0

    response = (
        client.table("assets")
        .update({"is_active": False})
        .not_.in_("kraken_pair", active_kraken_pairs)
        .eq("is_active", True)
        .execute()
    )

    count = len(response.data) if response.data else 0
    if count:
        log.info("mark_stale_assets_inactive: marked %d asset(s) inactive", count)
    return count
