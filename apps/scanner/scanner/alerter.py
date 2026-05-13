"""Alert Formatter + Discord Dispatcher — PR 11 / PR 22.

Formats Discord messages for clean and ugly candidates, enforces an 8-hour
deduplication window, POSTs to configured webhook URLs, and records every
delivery attempt to alerts_sent. On a successful POST, the corresponding
candidate_recommendations row is transitioned to state='alerted' and a
history row is written via state_machine.record_alerted_transition().

Public API:
    load_alert_config()                         -> AlertConfig | None
    format_table_messages(candidates, cat, ts)  -> list[str]  (compact table)
    format_candidate_embed(candidate)           -> dict[str, Any]  (legacy)
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

from scanner.models import ScoredCandidate, SelectionResult, TradeParameters
from scanner.settings import StrategySettings
from scanner.state_machine import record_alerted_transition

log = logging.getLogger(__name__)

# ── Discord embed colours (decimal) ──────────────────────────────────────────
_COLOR_CLEAN = 0x00C896  # teal-green — bullish confidence
_COLOR_UGLY = 0xF59E0B  # amber      — speculative / higher risk
_DISCORD_MAX_CHARS = 1900  # conservative limit; Discord hard cap is 2000


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


def load_alert_config(strategy: StrategySettings | None = None) -> AlertConfig | None:
    """Read Discord webhook URLs from environment variables.

    Returns None when required webhooks are absent, which gracefully
    disables alerting (Stage 8 is logged as skipped, not an error).

    When `strategy` is provided, its `scanner_alert_dedup_hours` value
    overrides the AlertConfig dedup window default. Webhook URLs always
    come from environment variables — never from the DB.
    """
    clean = os.getenv("DISCORD_WEBHOOK_CLEAN")
    ugly = os.getenv("DISCORD_WEBHOOK_UGLY")
    if not clean or not ugly:
        return None
    if strategy is not None:
        return AlertConfig(
            webhook_clean=clean,
            webhook_ugly=ugly,
            webhook_system=os.getenv("DISCORD_WEBHOOK_SYSTEM"),
            dedup_window_hours=strategy.scanner_alert_dedup_hours,
        )
    return AlertConfig(
        webhook_clean=clean,
        webhook_ugly=ugly,
        webhook_system=os.getenv("DISCORD_WEBHOOK_SYSTEM"),
    )


# ── Compact table formatting ──────────────────────────────────────────────────

#  Column widths (chars):  rank=2  symbol=8  entry=15  exit=12  stop=12  rr=5  size=7  score=5
_TABLE_HEADER = " #  Symbol    Entry            Exit          Stop          R:R    Size     Score"
_TABLE_SEP = " ── ────────  ───────────────  ────────────  ────────────  ─────  ───────  ─────"


def _fmt_price(price: float) -> str:
    """Format a price with adaptive decimal places for compact display."""
    if price >= 10_000:
        return f"{price:,.0f}"
    if price >= 1_000:
        return f"{price:,.1f}"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 10:
        return f"{price:.3f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.5f}"
    if price >= 0.0001:
        return f"{price:.7f}"
    return f"{price:.2e}"


def _fmt_entry(tp: TradeParameters) -> str:
    """Format entry zone as 'low–high' when both bounds are present."""
    if tp.entry_price_low is not None and tp.entry_price_high is not None:
        return f"{_fmt_price(tp.entry_price_low)}–{_fmt_price(tp.entry_price_high)}"
    return _fmt_price(tp.entry_price)


def _table_row(rank: int, candidate: ScoredCandidate) -> str:
    """Build one fixed-width table row for a candidate."""
    tp = candidate.trade
    score = candidate.score
    symbol = candidate.symbol[:8].ljust(8)
    entry = _fmt_entry(tp)[:15].ljust(15)
    exit_ = _fmt_price(tp.exit_price)[:12].ljust(12)
    stop = _fmt_price(tp.stop_loss)[:12].ljust(12)
    rr = f"{tp.reward_risk_ratio:.1f}x"[:5].ljust(5)
    size = tp.suggested_size_bucket[:7].ljust(7)
    sc = f"{score.score_total:.1f}"[:5]
    return f" {rank:<2} {symbol}  {entry}  {exit_}  {stop}  {rr}  {size}  {sc}"


def format_table_messages(
    candidates: list[ScoredCandidate],
    category: str,
    now_utc: str,
) -> list[str]:
    """Format candidates as compact monospace table message(s).

    Builds one or more Discord plain-text messages (each under
    _DISCORD_MAX_CHARS) containing a ```code-block``` table.
    Splits by rows when the full table would exceed the limit.

    Args:
        candidates: Ordered list of non-deduped candidates to include.
        category:   'clean' or 'ugly'.
        now_utc:    ISO-8601 UTC string used in the footer line.

    Returns:
        List of message strings, each safe to POST to a Discord webhook.
    """
    is_clean = category == "clean"
    emoji = "🟢" if is_clean else "🟡"
    label = "Clean" if is_clean else "Ugly"
    n = len(candidates)
    heading = f"{emoji} **{label} Candidates** — {n} setup{'s' if n != 1 else ''}"
    footer = f"*{now_utc}*"
    rows = [_table_row(i + 1, c) for i, c in enumerate(candidates)]

    def _build(subset: list[str]) -> str:
        body = "\n".join([_TABLE_HEADER, _TABLE_SEP] + subset)
        return f"{heading}\n```\n{body}\n```\n{footer}"

    messages: list[str] = []
    chunk: list[str] = []
    for row in rows:
        candidate_chunk = chunk + [row]
        if len(_build(candidate_chunk)) > _DISCORD_MAX_CHARS and chunk:
            messages.append(_build(chunk))
            chunk = [row]
        else:
            chunk = candidate_chunk
    if chunk:
        messages.append(_build(chunk))
    return messages


# ── Embed formatting (legacy) ────────────────────────────────────────────────────


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

    Per category (clean / ugly):
        1. Trim to max_n, resolve asset IDs, run dedup check per candidate.
        2. Format all qualifying candidates as a compact table message.
        3. POST each message chunk to the webhook (one POST per chunk).
        4. Insert one alerts_sent row per candidate (sent | failed together).
        5. On success: update state → 'alerted'; write state history row.

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
        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        to_alert: list[tuple[ScoredCandidate, str]] = []
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
            to_alert.append((candidate, asset_id))

        if not to_alert:
            return 0

        category = to_alert[0][0].category
        messages = format_table_messages([c for c, _ in to_alert], category, now_utc)
        shared_payload: dict[str, Any] = {"content": messages[0]}

        success = True
        err_msg: str | None = None
        for msg in messages:
            try:
                _post_to_webhook(webhook_url, {"content": msg})
            except Exception as exc:
                success = False
                err_msg = str(exc)
                log.warning(
                    "Discord POST failed for %s batch (channel=%s): %s",
                    category,
                    channel,
                    exc,
                )
                break

        sent = 0
        for candidate, asset_id in to_alert:
            _record_alert_sent(
                client,
                scan_run_id,
                asset_id,
                channel,
                webhook_url,
                shared_payload,
                success=success,
                error_message=err_msg,
            )
            if success:
                _update_recommendation_state(client, scan_run_id, asset_id, "alerted")
                record_alerted_transition(
                    client,
                    scan_run_id,
                    asset_id,
                    from_state=f"candidate_{candidate.category}",
                    metadata={
                        "symbol": candidate.symbol,
                        "rank": candidate.rank,
                        "score_total": candidate.score.score_total,
                    },
                )
                log.info(
                    "Discord alert recorded: %s rank=%d category=%s",
                    candidate.symbol,
                    candidate.rank,
                    candidate.category,
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
