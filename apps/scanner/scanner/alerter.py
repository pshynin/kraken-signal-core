"""Alert Formatter + Discord Dispatcher — PR 11 / PR 22.

Formats Discord messages for clean and ugly candidates, enforces a
configurable dedup window, POSTs to configured webhook URLs, and records
every delivery attempt to alerts_sent. On a successful POST, the
corresponding candidate_recommendations row is transitioned to
state='alerted' and a history row is written via
state_machine.record_alerted_transition().

The alert format is mobile-first stacked plain text wrapped in a
Discord embed for category visual identity (clean = green sidebar,
ugly = amber). See format_stacked_messages for the exact layout.

Public API:
    load_alert_config(strategy)                        -> AlertConfig | None
    format_stacked_messages(candidates, cat, when_utc) -> list[str]
    build_embed_payload(body, category)                -> dict[str, Any]
    run_alerter(client, scan_run_id,
                asset_id_map, selection_result,
                config)                                -> int  (alerts sent)

Environment variables (read by load_alert_config):
    DISCORD_WEBHOOK_CLEAN    Required. URL for the #clean-candidates channel.
    DISCORD_WEBHOOK_UGLY     Required. URL for the #ugly-candidates channel.
    DISCORD_WEBHOOK_SYSTEM   Optional. URL for the #system-alerts channel.

Deduplication:
    A 'new_candidate' alert is suppressed when alerts_sent already contains
    a row with delivery_status='sent' for the same asset_id within the last
    dedup_window_hours (default 8h; loaded from strategy_settings.scanner.
    alert_dedup_hours when a StrategySettings is passed to load_alert_config).

Webhook security:
    Actual webhook URLs are never stored in the database. Only a SHA-256
    hex digest is persisted in alerts_sent.webhook_url_hash.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from supabase import Client

from scanner.models import ScoredCandidate, SelectionResult
from scanner.settings import StrategySettings
from scanner.state_machine import record_alerted_transition

log = logging.getLogger(__name__)

# ── Discord embed colours (decimal) ──────────────────────────────────────────
_COLOR_CLEAN = 0x00C896  # teal-green — bullish confidence
_COLOR_UGLY = 0xF59E0B  # amber      — speculative / higher risk
# Per-message body cap. Lives inside an embed's `description` field
# (Discord cap: 4096 chars). Kept well below to leave headroom for the
# header line and any line-ending overhead.
_DISCORD_MAX_CHARS = 3500


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


# ── Stacked alert formatting (mobile-first) ───────────────────────────────────
#
# Each candidate renders as a four-line block:
#
#   #1 INJ • Prob 77% • Size 2k-5k
#   • Entry:  4.8883 (Max 4.9620)
#   • Exit:   6.3487 (Profit +30%)
#   • Stop:   4.3385 (Risk -11%)
#
# Title line: rank, ticker, probability, size bucket (separated by bullets).
# Field lines: bullet-prefixed label-then-value pairs, with Profit and Risk
# inline on the Exit and Stop lines. Profit and Risk percentages are derived
# from preferred_entry / exit_price / stop_loss (geometry), not from
# tp.expected_gain_pct.
#
# Blocks are separated by a blank line. The full body sits inside a Discord
# embed (`description` field) so we get a category-colour sidebar without
# forcing horizontal scrolling on mobile. No code-block table; no extra
# bot/product signature.


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


def _format_header(category: str, count: int, when_utc: datetime) -> str:
    """Build the single-line alert header.

    Example: '🟡 Ugly Candidates — 4 (<t:1747192500:R>)'
    The timestamp uses Discord's native <t:UNIX:R> markdown, which renders
    as a relative "N minutes/hours ago" string. The scanner runs on a UTC
    CI runner and cannot know each reader's timezone; emitting a raw Unix
    instant lets every Discord client compute the elapsed time locally.
    Discord's own message header already carries the absolute date, so a
    relative stamp reads naturally alongside it.
    """
    is_clean = category == "clean"
    emoji = "🟢" if is_clean else "🟡"
    label = "Clean" if is_clean else "Ugly"
    # Discord renders <t:UNIX:R> as a relative "N hours ago" string.
    # int() floors to whole seconds, which Discord expects.
    stamp = f"<t:{int(when_utc.timestamp())}:R>"
    return f"{emoji} {label} Candidates — {count} ({stamp})"


def _format_candidate_block(rank: int, candidate: ScoredCandidate) -> str:
    """Build one four-line stacked block for a candidate.

    Layout:
        #R SYM • Prob P% • Size BUCKET
        • Entry:  <preferred> (Max <max>)
        • Exit:   <exit> (Profit +X%)
        • Stop:   <stop> (Risk -X%)

    Profit % and Risk % are derived from preferred_entry / exit_price /
    stop_loss (geometry) so they cannot drift from the Entry/Exit/Stop
    prices shown on the same line. tp.expected_gain_pct is intentionally
    not read here.

    Label-value alignment: labels are left-padded to 8 chars so every
    value column starts at the same offset ("• Entry:  " = "• Exit:   "
    = "• Stop:   " = 10 chars before the value).

    Invariant: candidate.score.probability_pct must not be None for any
    alerted candidate (clean/ugly always score >= 62 per the probability
    map, so this is always set by the scorer). Violations fail loudly.
    """
    score = candidate.score
    if score.probability_pct is None:
        raise ValueError(
            f"alerter: probability_pct is None for {candidate.symbol} "
            f"({candidate.category} #{rank}) — clean/ugly candidates must "
            "have a populated probability"
        )

    tp = candidate.trade
    entry = tp.preferred_entry
    profit_pct = round((tp.exit_price - entry) / entry * 100)
    risk_pct = round((tp.stop_loss - entry) / entry * 100)

    title = (
        f"#{rank} {candidate.symbol} • "
        f"Prob {round(score.probability_pct)}% • "
        f"Size {tp.suggested_size_bucket}"
    )
    entry_line = f"• {'Entry:':<8}{_fmt_price(entry)} (Max {_fmt_price(tp.max_entry)})"
    exit_line = f"• {'Exit:':<8}{_fmt_price(tp.exit_price)} (Profit +{profit_pct}%)"
    stop_line = f"• {'Stop:':<8}{_fmt_price(tp.stop_loss)} (Risk {risk_pct}%)"
    return "\n".join([title, entry_line, exit_line, stop_line])


def format_stacked_messages(
    candidates: list[ScoredCandidate],
    category: str,
    when_utc: datetime,
) -> list[str]:
    """Format candidates as one or more stacked-text message bodies.

    Each returned string is the embed `description` body: a single-line
    header followed by per-candidate stacked blocks separated by blank
    lines. Splits between candidate blocks (never mid-block) when the
    body would exceed _DISCORD_MAX_CHARS.

    Args:
        candidates: Non-deduped candidates to include, in rank order.
        category:   'clean' or 'ugly'.
        when_utc:   UTC datetime used in the header timestamp.

    Returns:
        List of body strings, each safe to embed in a Discord webhook POST.
    """
    blocks = [_format_candidate_block(i + 1, c) for i, c in enumerate(candidates)]
    n = len(candidates)

    def _build(subset: list[str]) -> str:
        header = _format_header(category, n, when_utc)
        return header + "\n\n" + "\n\n".join(subset)

    if not blocks:
        return []

    messages: list[str] = []
    chunk: list[str] = []
    for block in blocks:
        candidate_chunk = chunk + [block]
        if len(_build(candidate_chunk)) > _DISCORD_MAX_CHARS and chunk:
            messages.append(_build(chunk))
            chunk = [block]
        else:
            chunk = candidate_chunk
    if chunk:
        messages.append(_build(chunk))
    return messages


def build_embed_payload(body: str, category: str) -> dict[str, Any]:
    """Wrap a rendered stacked body in a Discord embed payload.

    The embed gives clean/ugly its colour sidebar (visual identity) while
    keeping the body itself as plain stacked text for mobile readability.
    No title or footer is set — the header line is part of the body.
    """
    color = _COLOR_CLEAN if category == "clean" else _COLOR_UGLY
    return {"embeds": [{"description": body, "color": color}]}


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


_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)  # waits between attempts 1→2 and 2→3
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _post_to_webhook(url: str, payload: dict[str, Any]) -> None:
    """POST a Discord embed payload to a webhook URL, with bounded retry.

    Transient failures (connection/timeout errors, HTTP 429, HTTP 5xx) are
    retried up to _RETRY_MAX_ATTEMPTS total with exponential backoff. A
    Discord 429 carries a Retry-After header (seconds); it is honored when
    present, otherwise the static backoff is used. Permanent failures
    (4xx other than 429 — malformed payload, bad webhook) raise immediately
    since a retry cannot succeed.

    Raises:
        httpx.HTTPStatusError: on a non-retryable status, or after the
            final retry of a retryable status.
        httpx.RequestError: connection/timeout error after the final retry.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=10.0)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _RETRY_MAX_ATTEMPTS:
                retry_after = _parse_retry_after(resp)
                wait = (
                    retry_after if retry_after is not None else _RETRY_BACKOFF_SECONDS[attempt - 1]
                )
                log.warning(
                    "Discord POST got %d (attempt %d/%d) — retrying in %.1fs",
                    resp.status_code,
                    attempt,
                    _RETRY_MAX_ATTEMPTS,
                    wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()  # non-retryable 4xx, or final 5xx/429
            return
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= _RETRY_MAX_ATTEMPTS:
                raise
            wait = _RETRY_BACKOFF_SECONDS[attempt - 1]
            log.warning(
                "Discord POST connection error (attempt %d/%d): %s — retrying in %.1fs",
                attempt,
                _RETRY_MAX_ATTEMPTS,
                exc,
                wait,
            )
            time.sleep(wait)
    # Unreachable: the loop either returns, raises, or exhausts into the
    # final raise_for_status / RequestError raise above.
    if last_exc is not None:
        raise last_exc


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Extract a Retry-After value (seconds) from a Discord 429 response.

    Discord sends Retry-After as a number of seconds (may be fractional).
    Returns None when absent or unparseable so the caller falls back to
    the static backoff.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
        when_utc = datetime.now(UTC)

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
        bodies = format_stacked_messages([c for c, _ in to_alert], category, when_utc)
        payloads = [build_embed_payload(body, category) for body in bodies]
        # alerts_sent.payload captures the first message (representative of
        # the batch). Splits are an implementation detail of Discord's
        # length limits, not of the alert content.
        shared_payload: dict[str, Any] = payloads[0]

        success = True
        err_msg: str | None = None
        for payload in payloads:
            try:
                _post_to_webhook(webhook_url, payload)
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
