"""End-to-end integration smoke test.

Runs the full scanner pipeline in dry-run mode against the real Supabase
instance and Kraken API. Automatically skipped when SCANNER_ENV=test
(the default in unit CI — no credentials needed).

Run manually:
    SCANNER_ENV=development pytest tests/integration/ -v -m integration

Or via Docker:
    docker run --env-file .env kraken-scanner --dry-run
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
def test_full_pipeline_dry_run_exits_zero() -> None:
    """main(dry_run=True) must return 0 with real Kraken + Supabase access."""
    if os.environ.get("SCANNER_ENV", "test") == "test":
        pytest.skip("Integration test skipped in unit CI (SCANNER_ENV=test)")

    from scanner.main import main

    exit_code = main(dry_run=True)
    assert exit_code == 0, f"Scanner exited with code {exit_code} — check logs above"


@pytest.mark.integration
def test_universe_loads_minimum_assets() -> None:
    """Universe loader should return at least 100 tradable USD pairs from Kraken."""
    if os.environ.get("SCANNER_ENV", "test") == "test":
        pytest.skip("Integration test skipped in unit CI (SCANNER_ENV=test)")

    from scanner.universe import load_universe

    universe = load_universe()
    assert len(universe) >= 100, f"Expected ≥100 universe assets, got {len(universe)}"
    assert all(item.symbol for item in universe)
    assert all(item.kraken_pair for item in universe)
