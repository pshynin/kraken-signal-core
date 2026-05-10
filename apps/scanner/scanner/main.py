"""Crypto Momentum Alert Copilot — Scanner entry point.

Usage:
    python -m scanner.main
    python -m scanner.main --dry-run

Pipeline stages:
    1. Universe loader        ✅ PR 4
    2. Market data fetcher       PR 5
    3. Indicator engine          PR 6
    4. Hard filter               PR 7
    5. Metric calculator         PR 7
    6. Scoring engine            PR 8
    7. Candidate selector        PR 9
    8. State machine             PR 10
    9. Run persister             PR 10
    10. Alert dispatcher         PR 11
"""

from __future__ import annotations

import argparse
import logging
import os
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

    log.info("Crypto Momentum Alert Copilot — Scanner starting | dry_run=%s", dry_run)

    # ── Stage 1: Universe loader ───────────────────────────────────────────────
    from scanner.config import load_config
    from scanner.universe import load_universe

    try:
        cfg = load_config(dry_run=dry_run)
    except OSError as exc:
        log.error("Configuration error: %s", exc)
        return 1

    log.info("Stage 1 — loading Kraken universe")
    try:
        universe = load_universe()
    except Exception as exc:
        log.exception("Universe load failed: %s", exc)
        return 1

    log.info("Universe: %d tradable USD spot pairs", len(universe))
    for item in universe[:5]:
        log.debug("  %s (%s) ordermin=%.8f", item.symbol, item.kraken_pair, item.min_order_size)

    # ── DB write (skip on dry_run or missing credentials) ─────────────────────
    db_client = None
    scan_run_id: str | None = None
    _do_db = not dry_run and cfg.scanner_env != "test" and bool(cfg.supabase_url)

    if _do_db:
        from scanner.db import get_client, mark_stale_assets_inactive, upsert_assets
        from scanner.persister import create_scan_run

        db_client = get_client(cfg)
        log.info("Stage 1 — upserting %d assets to DB", len(universe))
        upsert_assets(db_client, universe)
        mark_stale_assets_inactive(db_client, [item.kraken_pair for item in universe])

        triggered_by = os.getenv("SCANNER_TRIGGERED_BY", "manual")
        scanner_version = os.getenv("SCANNER_VERSION")
        scan_run_id = create_scan_run(
            db_client,
            triggered_by=triggered_by,
            scanner_version=scanner_version,
        )
        log.info("Stage 1 — scan run created: %s", scan_run_id)
    else:
        log.info("Stage 1 — skipping DB write (dry_run=%s, env=%s)", dry_run, cfg.scanner_env)

    # ── Stage 2: Market data fetcher ──────────────────────────────────────────
    from scanner.fetcher import fetch_market_data

    log.info("Stage 2 — fetching OHLCV market data")
    fetch_result = fetch_market_data(universe)

    if fetch_result.success_count == 0:
        log.error("Stage 2 failed: no assets returned OHLCV data")
        return 1

    if fetch_result.failed_symbols:
        log.warning(
            "Stage 2 partial: %d asset(s) failed to fetch and will be excluded — %s",
            fetch_result.failure_count,
            fetch_result.failed_symbols,
        )

    log.info(
        "Stage 2 complete: %d/%d assets ready for indicator engine",
        fetch_result.success_count,
        fetch_result.total_count,
    )

    # ── Stage 3: Indicator engine ──────────────────────────────────────────────
    from scanner.indicators import run_indicator_engine

    log.info("Stage 3 — computing technical indicators")
    indicator_result = run_indicator_engine(fetch_result.successful)

    if indicator_result.success_count == 0:
        log.error("Stage 3 failed: no assets produced indicator snapshots")
        return 1

    if indicator_result.failed_symbols:
        log.warning(
            "Stage 3 partial: %d asset(s) failed indicator computation — %s",
            indicator_result.failure_count,
            indicator_result.failed_symbols,
        )

    log.info(
        "Stage 3 complete: %d/%d assets have indicators ready for scoring",
        indicator_result.success_count,
        indicator_result.total_count,
    )

    # ── Stage 4: Hard filter + market metrics ─────────────────────────────────
    from scanner.filter import run_hard_filter

    log.info("Stage 4 — computing market metrics and applying hard filter")
    filter_result = run_hard_filter(
        fetch_result.successful,
        indicator_result.successful,
    )

    if filter_result.passed_count == 0:
        log.error("Stage 4: all assets excluded by hard filter")
        return 1

    log.info(
        "Stage 4 complete: %d passed / %d excluded (pass rate %.0f%%)",
        filter_result.passed_count,
        filter_result.excluded_count,
        filter_result.pass_rate * 100,
    )

    # ── Stage 5: Scoring engine ────────────────────────────────────────────────
    from scanner.scoring import run_scoring_engine

    log.info("Stage 5 — scoring %d assets", filter_result.passed_count)
    scoring_result = run_scoring_engine(filter_result)

    log.info(
        "Stage 5 complete: clean=%d ugly=%d watchlist=%d",
        scoring_result.clean_count,
        scoring_result.ugly_count,
        len(scoring_result.watchlist),
    )

    # ── Stage 6: Candidate selector + trade parameters ────────────────────────
    from scanner.selector import run_candidate_selector

    log.info("Stage 6 — selecting candidates and computing trade parameters")
    selection_result = run_candidate_selector(scoring_result, filter_result)

    if selection_result.total_count == 0:
        log.warning("Stage 6: no candidates selected (clean=0, ugly=0)")
    else:
        log.info(
            "Stage 6 complete: %d clean + %d ugly candidates",
            len(selection_result.clean),
            len(selection_result.ugly),
        )

    # ── Stage 7: Run persister (DB writes + state machine) ───────────────────
    asset_id_map: dict[str, str] = {}
    _persist_ok = False

    if _do_db and db_client and scan_run_id:
        from scanner.persister import fail_scan_run, persist_run

        log.info("Stage 7 — persisting run data to Supabase")
        try:
            asset_id_map = persist_run(
                db_client,
                scan_run_id,
                filter_result=filter_result,
                scoring_result=scoring_result,
                selection_result=selection_result,
            )
            _persist_ok = True
            log.info("Stage 7 complete — all tables written")
        except Exception as exc:
            log.exception("Stage 7 failed: %s", exc)
            fail_scan_run(db_client, scan_run_id, error_message=str(exc))
    else:
        log.info(
            "Stage 7 — skipping DB writes (dry_run=%s). %d candidates computed in-memory.",
            dry_run,
            selection_result.total_count,
        )

    # ── Stage 8: Discord alerts ───────────────────────────────────────────────
    alerts_sent_count = 0

    if _do_db and db_client and scan_run_id and _persist_ok and asset_id_map:
        from scanner.alerter import load_alert_config, run_alerter

        alert_config = load_alert_config()
        if alert_config:
            log.info("Stage 8 — sending Discord alerts")
            try:
                alerts_sent_count = run_alerter(
                    db_client,
                    scan_run_id,
                    asset_id_map,
                    selection_result,
                    alert_config,
                )
                log.info("Stage 8 complete — %d alerts sent", alerts_sent_count)
            except Exception as exc:
                log.exception("Stage 8 failed: %s", exc)
        else:
            log.warning(
                "Stage 8 — Discord webhooks not configured "
                "(set DISCORD_WEBHOOK_CLEAN and DISCORD_WEBHOOK_UGLY to enable)"
            )
    elif not _do_db:
        log.info("Stage 8 — skipping alerts (dry_run=%s)", dry_run)

    # ── Finalise scan run record ──────────────────────────────────────────────
    if _do_db and db_client and scan_run_id:
        from scanner.persister import complete_scan_run

        status = "completed" if _persist_ok else "partial"
        complete_scan_run(
            db_client,
            scan_run_id,
            status=status,
            assets_scanned=fetch_result.total_count,
            assets_passed_filter=filter_result.passed_count,
            candidates_clean=len(selection_result.clean),
            candidates_ugly=len(selection_result.ugly),
            alerts_sent=alerts_sent_count,
        )

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
