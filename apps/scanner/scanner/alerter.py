"""Alert Formatter + Discord Dispatcher — PR 11.

Formats Discord embeds for clean and ugly candidates, enforces an 8-hour
deduplication window, POSTs to configured webhook URLs, and records every
delivery attempt to alerts_sent. On a successful POST, the corresponding
candidate_recommendations row is transitioned to state='alerted' and a
history row is written via state_machine.record_alerted_transition().

Public API:
    load_alert_config()                         -> AlertConfig | None
    format_candidate_embed(candidate)           -> dict[str, Any]
    run_alerter(client, scan_run_id,
                asset_id_map, selection_result,
                config)                         -> int  (alerts sent)

Environment variables (read by load_alert_config):
    DISCORD_WEBHOOK_CLEAN    Required. URL for the #clean-candidates channel.
    DISCORD_WEBHOOK_UGLY     Required. URL for the #ugly-candidates channel.
    DISCORD_WEBHOOK_SYSTEM   Optional. URL for the #system-alerts channel.

Deduplication:
    A 'new_candidate' alert is suppressed when alerts_sent already contains
    a row with delivery_status='sent' for the same asset_id within the last
    dedup_window_hours (default: 8 h). This prevents re-alerting the same
    coin across consecutive scans.

Webhook security:
    Actual webhook URLs are never stored in the database. Only a SHA-256
    hex digest is persisted in alerts_sent.webhook_url_hash.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from supabase import Client

from scanner.models import ScoredCandidate, SelectionResult
from scanner.state_machine import record_alerted_transition

log = logging.getLogger(__name__)

# ── Discord embed colours (decimal) ──────────────────────────────────────────
_COLOR_CLEAN = 0x00C896  # teal-green — bullish confidence
_COLOR_UGLY = 0xF59E0B  # amber      — speculative / higher risk


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlertConfig:
    """Discord alert thresholds and webhook routing.

    All webhook URLs live in environment variables only — never in code or DB.
    """

    webhook_clean: str
    webhook_ugly: str
    webhook_system: str | None = None
    dedup_window_hours: int = 8
    """Hours before the same asset can be re-alerted as a new_candidate."""
    max_clean_alerts: int = 5
    """Safety cap: at most this many clean alerts per scanner run."""
    max_ugly_alerts: int = 5
    """Safety cap: at most this many ugly alerts per scanner run."""


def load_alert_config() -> AlertConfig | None:
    """Read Discord webhook URLs from environment variables.

    Returns None when required webhooks are absent, which gracefully
    disables alerting (Stage 8 is logged as skipped, not an error).
    """
    clean = os.getenv("DISCORD_WEBHOOK_CLEAN")
    ugly = os.getenv("DISCORD_WEBHOOK_UGLY")
    if not clean or not ugly:
        return None
    return AlertConfig(
        webhook_clean=clean,
        webhook_ugly=ugly,
        webhook_system=os.getenv("DISCORD_WEBHOOK_SYSTEM"),
    )


# ── Embed formatting ──────────────────────────────────────────────────────────


def format_candidate_embed(candidate: ScoredCandidate) -> dict[str, Any]:
    """Build a Discord embed dict for one clean or ugly candidate.

    Layout (mobile-friendly):
        Title:       {emoji} {SYMBOL}  —  {Category} Candidate #{rank}
        Description: compact indicator summary from trade.notes
        6 inline fields: Entry Zone | Exit Target | Stop Loss
                          R:R Ratio  | Size Bucket | Score
        Footer + ISO timestamp

    Args:
        candidate: A ScoredCandidate from SelectionResult.

    Returns:
        A dict ready to be placed in a Discord "embeds" array.
    """
    is_clean = candidate.category == "clean"
    emoji = "🟢" if is_clean else "🟡"
    cat_label = "Clean" if is_clean else "Ugly"
    color = _COLOR_CLEAN if is_clean else _COLOR_UGLY

    tp = candidate.trade
    score = candidate.score
    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    stop_pct = abs((tp.stop_loss - tp.entry_price) / tp.entry_price * 100)

    if tp.entry_price_low is not None and tp.entry_price_high is not None:
        entry_zone_value = f"${tp.entry_price_low:,.4f} – ${tp.entry_price_high:,.4f}"
    else:
        entry_zone_value = f"${tp.entry_price:,.4f}"

    fields: list[dict[str, Any]] = [
        {
            "name": "Entry Zone",
            "value": entry_zone_value,
            "inline": True,
        },
        {
            "name": "Exit Target",
            "value": f"${tp.exit_price:,.4f}  (+{tp.expected_gain_pct:.1f}%)",
            "inline": True,
        },
        {
            "name": "Stop Loss",
            "value": f"${tp.stop_loss:,.4f}  (-{stop_pct:.1f}%)",
            "inline": True,
        },
        {
            "name": "R:R Ratio",
            "value": f"{tp.reward_risk_ratio:.2f}×",
            "inline": True,
        },
        {
            "name": "Size Bucket",
            "value": tp.suggested_size_bucket,
            "inline": True,
        },
        {
            "name": "Score",
            "value": f"{score.score_total:.1f} / 100  (prob: {score.probability_pct:.0f}%)",
            "inline": True,
        },
    ]

    return {
        "title": f"{emoji} {candidate.symbol}  —  {cat_label} Candidate #{candidate.rank}",
        "description": tp.notes or "",
        "color": color,
        "fields": fields,
        "footer": {"text": "Kraken Signal"},
        "timestamp": now_utc,
    }


# ── Deduplication ─────────────────────────────────────────────────────────────


def _is_already_alerted(
    client: Client,
    asset_id: str,
    cutoff_iso: str,
) -> bool:
    """Return True if a successful new_candidate alert was sent recently.

    Queries alerts_sent for rows matching (asset_id, new_candidate, sent,
    sent_at > cutoff). Returns True if any such row exists.
    """
    resp = (
        client.table("alerts_sent")
        .select("id")
        .eq("asset_id", asset_id)
        .eq("alert_type", "new_candidate")
        .eq("delivery_status", "sent")
        .gte("sent_at", cutoff_iso)
        .execute()
    )
    data = cast(list[dict[str, Any]], resp.data or [])
    return len(data) > 0


# ── Webhook POST ──────────────────────────────────────────────────────────────


def _post_to_webhook(url: str, payload: dict[str, Any]) -> None:
    """POST a Discord embed payload to a webhook URL.

    Discord webhooks accept up to 30 requests/min per URL. The scanner sends
    at most 10 alerts per run (5 clean + 5 ugly) so no rate-limit handling
    is required beyond the default httpx timeout.

    Raises:
        httpx.HTTPStatusError: on non-2xx responses.
        httpx.TimeoutException: if the server does not respond within 10 s.
    """
    resp = httpx.post(url, json=payload, timeout=10.0)
    resp.raise_for_status()


# ── DB helpers ────────────────────────────────────────────────────────────────


def _record_alert_sent(
    client: Client,
    scan_run_id: str,
    asset_id: str,
    channel: str,
    webhook_url: str,
    payload: dict[str, Any],
    *,
    success: bool,
    error_message: str | None,
) -> None:
    """Insert one row into alerts_sent with final delivery status."""
    now_iso = datetime.now(UTC).isoformat()
    row: dict[str, Any] = {
        "scan_run_id": scan_run_id,
        "asset_id": asset_id,
        "alert_type": "new_candidate",
        "channel": channel,
        "webhook_url_hash": hashlib.sha256(webhook_url.encode()).hexdigest(),
        "payload": payload,
        "delivery_status": "sent" if success else "failed",
        "sent_at": now_iso if success else None,
        "error_message": error_message,
    }
    client.table("alerts_sent").insert(row).execute()


def _update_recommendation_state(
    client: Client,
    scan_run_id: str,
    asset_id: str,
    state: str,
) -> None:
    """Update candidate_recommendations.state for (scan_run_id, asset_id)."""
    (
        client.table("candidate_recommendations")
        .update({"state": state})
        .eq("scan_run_id", scan_run_id)
        .eq("asset_id", asset_id)
        .execute()
    )


# ── Pipeline entry point ──────────────────────────────────────────────────────


def run_alerter(
    client: Client,
    scan_run_id: str,
    asset_id_map: dict[str, str],
    selection_result: SelectionResult,
    config: AlertConfig,
) -> int:
    """Send Discord alerts for new clean + ugly candidates.

    For each candidate (up to max_clean / max_ugly per run):
        1. Dedup check — skip if already alerted within dedup_window_hours.
        2. Format Discord embed.
        3. POST to webhook (httpx, synchronous, 10 s timeout).
        4. Insert alerts_sent row (delivery_status = sent | failed).
        5. On success only:
               update candidate_recommendations.state → 'alerted'
               write asset_state_history: candidate_* → alerted

    Args:
        asset_id_map:     {symbol: asset_uuid} — returned by persist_run().
        selection_result: Stage 6 output containing clean + ugly candidates.
        config:           AlertConfig with webhook URLs and thresholds.

    Returns:
        Total number of alerts successfully delivered (POSTed + recorded).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=config.dedup_window_hours)
    cutoff_iso = cutoff.isoformat()
    total_sent = 0

    def _alert_batch(
        candidates: list[ScoredCandidate],
        webhook_url: str,
        channel: str,
        max_n: int,
    ) -> int:
        sent = 0
        for candidate in candidates[:max_n]:
            asset_id = asset_id_map.get(candidate.symbol)
            if not asset_id:
                log.warning("run_alerter: no asset_id for %s — skipping", candidate.symbol)
                continue

            if _is_already_alerted(client, asset_id, cutoff_iso):
                log.info(
                    "%s already alerted within %dh window — skipping",
                    candidate.symbol,
                    config.dedup_window_hours,
                )
                continue

            embed = format_candidate_embed(candidate)
            payload: dict[str, Any] = {"embeds": [embed]}
            success = False
            err_msg: str | None = None

            try:
                _post_to_webhook(webhook_url, payload)
                success = True
                log.info(
                    "Discord alert sent: %s  rank=%d  category=%s",
                    candidate.symbol,
                    candidate.rank,
                    candidate.category,
                )
            except Exception as exc:
                err_msg = str(exc)
                log.warning("Discord POST failed for %s: %s", candidate.symbol, exc)

            _record_alert_sent(
                client,
                scan_run_id,
                asset_id,
                channel,
                webhook_url,
                payload,
                success=success,
                error_message=err_msg,
            )

            if success:
                from_state = f"candidate_{candidate.category}"
                _update_recommendation_state(client, scan_run_id, asset_id, "alerted")
                record_alerted_transition(
                    client,
                    scan_run_id,
                    asset_id,
                    from_state=from_state,
                    metadata={
                        "symbol": candidate.symbol,
                        "rank": candidate.rank,
                        "score_total": candidate.score.score_total,
                    },
                )
                sent += 1

        return sent

    total_sent += _alert_batch(
        selection_result.clean,
        config.webhook_clean,
        "discord_clean",
        config.max_clean_alerts,
    )
    total_sent += _alert_batch(
        selection_result.ugly,
        config.webhook_ugly,
        "discord_ugly",
        config.max_ugly_alerts,
    )

    log.info("run_alerter complete: %d/%d alerts sent", total_sent, selection_result.total_count)
    return total_sent
