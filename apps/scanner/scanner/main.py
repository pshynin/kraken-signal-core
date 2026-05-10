"""Crypto Momentum Alert Copilot — Scanner entry point.

Usage:
    python -m scanner.main
    python -m scanner.main --dry-run

Pipeline stages (added across PRs 4–12):
    1. Universe loader        (PR 4)
    2. Market data fetcher    (PR 5)
    3. Indicator engine       (PR 6)
    4. Hard filter            (PR 7)
    5. Metric calculator      (PR 7)
    6. Scoring engine         (PR 8)
    7. Candidate selector     (PR 9)
    8. State machine          (PR 10)
    9. Run persister          (PR 10)
    10. Alert dispatcher      (PR 11)
"""

from __future__ import annotations

import argparse
import logging
import sys


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )


def main(dry_run: bool = False) -> int:
    _configure_logging()
    log = logging.getLogger(__name__)

    log.info("Crypto Momentum Alert Copilot — Scanner starting")
    log.info("Version: scaffold (PR 1 of 18) | dry_run=%s", dry_run)
    log.warning("Pipeline not yet implemented. PRs 4–12 build the full scan execution pipeline.")

    print()
    print("Crypto Momentum Alert Copilot — Scanner Service")
    print("Status : scaffold only — pipeline not yet implemented.")
    print("Next   : PR 2 (schema) → PR 4 (universe) → PR 5 (data) → ...")
    print()

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Kraken Signal Scanner — Crypto Momentum Alert Copilot",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing to the database or sending Discord alerts.",
    )
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
