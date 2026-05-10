"""Scanner runtime configuration — loaded once at startup from environment variables.

Priority order (highest to lowest):
  1. Real environment variables (set by GitHub Actions / Docker)
  2. .env file in the working directory (local development)
  3. Hard defaults where safe (non-secret values only)

Usage:
    from scanner.config import load_config
    cfg = load_config(dry_run=args.dry_run)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env if present — no-op if running in CI with vars already set
load_dotenv()


@dataclass(frozen=True)
class ScannerConfig:
    supabase_url: str
    supabase_service_role_key: str
    scanner_env: str  # "development" | "test" | "production"
    dry_run: bool


def load_config(dry_run: bool = False) -> ScannerConfig:
    """Load and return validated scanner configuration.

    In test mode (SCANNER_ENV=test), Supabase credentials are not required
    since unit tests never hit the real database.

    Raises:
        EnvironmentError: if required variables are missing in non-test mode.
    """
    scanner_env = os.environ.get("SCANNER_ENV", "development")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if scanner_env != "test":
        if not url:
            raise OSError("SUPABASE_URL is required. Set it in your .env file or environment.")
        if not key:
            raise OSError(
                "SUPABASE_SERVICE_ROLE_KEY is required. Set it in your .env file or environment."
            )

    return ScannerConfig(
        supabase_url=url,
        supabase_service_role_key=key,
        scanner_env=scanner_env,
        dry_run=dry_run,
    )
