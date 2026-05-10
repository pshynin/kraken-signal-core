"""Pytest configuration for the scanner test suite.

Sets safe environment variable defaults so tests never require
real Supabase credentials or live Kraken API access.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_test_env() -> None:
    """Inject safe defaults for all required environment variables."""
    os.environ.setdefault("SCANNER_ENV", "test")
    os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    os.environ.setdefault("DISCORD_WEBHOOK_CLEAN", "https://discord.com/api/webhooks/test/clean")
    os.environ.setdefault("DISCORD_WEBHOOK_UGLY", "https://discord.com/api/webhooks/test/ugly")
    os.environ.setdefault("DISCORD_WEBHOOK_SYSTEM", "https://discord.com/api/webhooks/test/system")
