"""Trade outcome computation — PR H2 (validation tooling).

Read-only. Given a persisted candidate_recommendations row and the forward
price path for that asset, compute what would have happened to the trade
over the fixed 10-day horizon: did it fill, did it hit the stop, did it
hit the target, what were the adverse/favorable excursions.

This module is split into a pure deterministic core (no DB, no clock —
fully unit-testable with synthetic price paths) and a thin Supabase
reading layer that assembles the inputs.

Locked semantics (see plan validation-tooling-hij.md):
  - Fill: price enters [preferred_entry, max_entry] (i.e. low <= max_entry)
    at any point within the horizon.
  - Horizon: 10 days. Unfilled by day 10 -> NO_FILL. Filled but neither
    stop nor target by day 10 -> EXPIRED_OPEN, marked-to-market at the
    last close in the horizon.
  - Stop/target same-candle ambiguity: STOP FIRST (pessimistic). If a
    candle's range spans both stop and target we count the stop.
  - MAE/MFE: measured from the fill price, filled trades only.
  - Fidelity: a single label per trade. EXACT when ohlcv_candles cover
    the entire horizon (real high/low); CLOSE_APPROX when any part of
    the horizon falls back to market_snapshots 6h closes (high=low=close,
    so fill/stop/target detection degrades to "did the close cross").
    Whole-trade fidelity is the lowest available across the horizon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from supabase import Client

log = logging.getLogger(__name__)

HORIZON_DAYS = 10
"""Fixed trade horizon — the README's 10-day cycle. Both the fill window and
the post-fill management window live inside this single 10-day span."""


class Fidelity(StrEnum):
    """How trustworthy a trade's outcome is, given the price source."""

    EXACT = "exact"  # ohlcv_candles covered the whole horizon (real high/low)
    CLOSE_APPROX = "close_approx"  # some/all of the horizon was 6h-close only


class OutcomeKind(StrEnum):
    """Terminal classification of a trade over the horizon."""

    NO_FILL = "no_fill"  # entry zone never reached
    TARGET_HIT = "target_hit"  # filled, then reached exit_price
    STOP_HIT = "stop_hit"  # filled, then hit stop_loss (or both same candle)
    EXPIRED_OPEN = "expired_open"  # filled, neither stop nor target by day 10


@dataclass(frozen=True)
class ForwardCandle:
    """One step of the forward price path, normalized across sources.

    From ohlcv_candles: real high/low/close. From market_snapshots: a
    single price, stored as high == low == close (the degenerate
    close-approx case — range detection collapses to a close crossing).
    """

    timestamp: datetime
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class TradeSpec:
    """The trade definition extracted from a candidate_recommendations row."""

    symbol: str
    scan_run_id: str
    category: str  # 'clean' | 'ugly'
    setup_type: str | None
    scan_time: datetime  # when the recommendation was produced
    preferred_entry: float
    max_entry: float
    exit_price: float
    stop_loss: float
    probability_pct: float | None
    size_bucket: str


@dataclass(frozen=True)
class TradeOutcome:
    """Computed result for one trade over the horizon. Never persisted —
    PR I aggregates these on demand."""

    symbol: str
    scan_run_id: str
    category: str
    setup_type: str | None
    size_bucket: str
    probability_pct: float | None

    kind: OutcomeKind
    fidelity: Fidelity

    filled: bool
    fill_time: datetime | None
    exit_time: datetime | None
    days_to_fill: float | None
    days_to_exit: float | None

    # Realized return at the terminal event, as a fraction of the fill price
    # (e.g. 0.18 = +18%). None when the trade never filled.
    realized_return: float | None

    # Max adverse / favorable excursion as fractions of the fill price,
    # measured only after fill. mae <= 0, mfe >= 0. None when never filled.
    mae: float | None
    mfe: float | None


# ── Pure deterministic core ───────────────────────────────────────────────────


def compute_outcome(
    spec: TradeSpec,
    forward: list[ForwardCandle],
    fidelity: Fidelity,
    horizon_days: int = HORIZON_DAYS,
) -> TradeOutcome:
    """Compute the trade outcome from a spec and its forward price path.

    Pure and deterministic: same inputs -> same output. No DB, no clock.

    `forward` must be ordered ascending by timestamp and should already be
    clipped to the horizon by the caller, but this function defensively
    stops at scan_time + horizon_days regardless.
    """
    horizon_end = spec.scan_time + timedelta(days=horizon_days)

    fill_time: datetime | None = None
    fill_price: float | None = None

    # ── Phase 1: find the fill ────────────────────────────────────────────────
    # Fill = the candle's low reaches into [.., max_entry]. We enter at
    # min(max_entry, candle close) is tempting, but the locked rule is
    # simply "price entered the zone": model the fill at preferred_entry
    # when the candle traded through it, else at max_entry (the worst
    # in-zone price we'd have accepted on a chase).
    fill_idx: int | None = None
    for i, c in enumerate(forward):
        if c.timestamp > horizon_end:
            break
        if c.low <= spec.max_entry:
            fill_time = c.timestamp
            if c.low <= spec.preferred_entry:
                fill_price = spec.preferred_entry
            else:
                # Zone was entered but never down to preferred — filled on
                # the chase; worst acceptable price is max_entry.
                fill_price = min(spec.max_entry, c.high)
            fill_idx = i
            break

    if fill_idx is None or fill_time is None or fill_price is None:
        return TradeOutcome(
            symbol=spec.symbol,
            scan_run_id=spec.scan_run_id,
            category=spec.category,
            setup_type=spec.setup_type,
            size_bucket=spec.size_bucket,
            probability_pct=spec.probability_pct,
            kind=OutcomeKind.NO_FILL,
            fidelity=fidelity,
            filled=False,
            fill_time=None,
            exit_time=None,
            days_to_fill=None,
            days_to_exit=None,
            realized_return=None,
            mae=None,
            mfe=None,
        )

    days_to_fill = (fill_time - spec.scan_time).total_seconds() / 86400.0

    # ── Phase 2: walk forward from the fill, tracking excursions ──────────────
    mae = 0.0  # most adverse (lowest) excursion, fraction of fill price (<= 0)
    mfe = 0.0  # most favorable (highest) excursion (>= 0)
    last_close = fill_price

    for c in forward[fill_idx:]:
        if c.timestamp > horizon_end:
            break
        last_close = c.close

        # Update excursions from the candle extremes (post-fill only).
        low_exc = (c.low - fill_price) / fill_price
        high_exc = (c.high - fill_price) / fill_price
        mae = min(mae, low_exc)
        mfe = max(mfe, high_exc)

        hit_stop = c.low <= spec.stop_loss
        hit_target = c.high >= spec.exit_price

        if hit_stop and hit_target:
            # Same-candle ambiguity -> STOP FIRST (pessimistic, locked).
            return _terminal(
                spec,
                fidelity,
                fill_time,
                fill_price,
                c.timestamp,
                spec.stop_loss,
                OutcomeKind.STOP_HIT,
                days_to_fill,
                mae,
                mfe,
            )
        if hit_stop:
            return _terminal(
                spec,
                fidelity,
                fill_time,
                fill_price,
                c.timestamp,
                spec.stop_loss,
                OutcomeKind.STOP_HIT,
                days_to_fill,
                mae,
                mfe,
            )
        if hit_target:
            return _terminal(
                spec,
                fidelity,
                fill_time,
                fill_price,
                c.timestamp,
                spec.exit_price,
                OutcomeKind.TARGET_HIT,
                days_to_fill,
                mae,
                mfe,
            )

    # ── Phase 3: horizon expired with the trade still open ────────────────────
    # Mark to market at the last close seen within the horizon.
    return _terminal(
        spec,
        fidelity,
        fill_time,
        fill_price,
        None,
        last_close,
        OutcomeKind.EXPIRED_OPEN,
        days_to_fill,
        mae,
        mfe,
    )


def _terminal(
    spec: TradeSpec,
    fidelity: Fidelity,
    fill_time: datetime,
    fill_price: float,
    exit_time: datetime | None,
    exit_at: float,
    kind: OutcomeKind,
    days_to_fill: float,
    mae: float,
    mfe: float,
) -> TradeOutcome:
    """Build a filled-trade TradeOutcome. exit_time is None for EXPIRED_OPEN
    (no discrete event — marked to market at the last close)."""
    realized = (exit_at - fill_price) / fill_price
    days_to_exit = (
        (exit_time - fill_time).total_seconds() / 86400.0 if exit_time is not None else None
    )
    return TradeOutcome(
        symbol=spec.symbol,
        scan_run_id=spec.scan_run_id,
        category=spec.category,
        setup_type=spec.setup_type,
        size_bucket=spec.size_bucket,
        probability_pct=spec.probability_pct,
        kind=kind,
        fidelity=fidelity,
        filled=True,
        fill_time=fill_time,
        exit_time=exit_time,
        days_to_fill=round(days_to_fill, 4),
        days_to_exit=round(days_to_exit, 4) if days_to_exit is not None else None,
        realized_return=round(realized, 6),
        mae=round(mae, 6),
        mfe=round(mfe, 6),
    )


# ── Supabase reading layer (thin; assembles inputs for the pure core) ─────────


def _parse_ts(raw: str) -> datetime:
    """Parse a Supabase timestamptz string to an aware datetime."""
    return datetime.fromisoformat(raw)


def fetch_trade_specs(
    client: Client,
    *,
    since: datetime | None = None,
) -> list[TradeSpec]:
    """Read candidate_recommendations (joined to assets + scan_runs) into
    TradeSpec objects. `since` filters by scan_runs.started_at when given.
    """
    q = client.table("candidate_recommendations").select(
        "category, setup_type, preferred_entry, max_entry, entry_price, "
        "exit_price, stop_loss, probability_pct, suggested_size_bucket, "
        "scan_run_id, "
        "assets ( symbol ), "
        "scan_runs ( started_at )"
    )
    resp = q.execute()
    rows = cast(list[dict[str, Any]], resp.data or [])

    specs: list[TradeSpec] = []
    for r in rows:
        scan_runs = r.get("scan_runs") or {}
        started_at = scan_runs.get("started_at")
        if not started_at:
            continue
        scan_time = _parse_ts(started_at)
        if since is not None and scan_time < since:
            continue

        assets = r.get("assets") or {}
        # preferred_entry / max_entry are post-PR-entry-engine columns; fall
        # back to entry_price for older rows that predate them.
        preferred = r.get("preferred_entry")
        max_entry = r.get("max_entry")
        entry_price = r["entry_price"]
        specs.append(
            TradeSpec(
                symbol=str(assets.get("symbol", "???")),
                scan_run_id=str(r["scan_run_id"]),
                category=str(r["category"]),
                setup_type=(str(r["setup_type"]) if r.get("setup_type") is not None else None),
                scan_time=scan_time,
                preferred_entry=float(preferred if preferred is not None else entry_price),
                max_entry=float(max_entry if max_entry is not None else entry_price),
                exit_price=float(r["exit_price"]),
                stop_loss=float(r["stop_loss"]),
                probability_pct=(
                    float(r["probability_pct"]) if r.get("probability_pct") is not None else None
                ),
                size_bucket=str(r["suggested_size_bucket"]),
            )
        )
    return specs


def fetch_forward_path(
    client: Client,
    symbol: str,
    asset_id: str,
    start: datetime,
    horizon_days: int = HORIZON_DAYS,
) -> tuple[list[ForwardCandle], Fidelity]:
    """Assemble the forward price path for one trade and decide its fidelity.

    Prefers ohlcv_candles (real high/low). If ohlcv_candles do not cover the
    full [start, start+horizon] window, falls back to market_snapshots
    closes for the gap and downgrades the whole-trade fidelity to
    CLOSE_APPROX (lowest available across the horizon — the locked rule).
    """
    end = start + timedelta(days=horizon_days)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    ohlcv_resp = (
        client.table("ohlcv_candles")
        .select("candle_timestamp, high, low, close")
        .eq("asset_id", asset_id)
        .eq("timeframe", "4h")
        .gte("candle_timestamp", start_iso)
        .lte("candle_timestamp", end_iso)
        .order("candle_timestamp", desc=False)
        .execute()
    )
    ohlcv_rows = cast(list[dict[str, Any]], ohlcv_resp.data or [])

    if ohlcv_rows:
        candles = [
            ForwardCandle(
                timestamp=_parse_ts(str(row["candle_timestamp"])),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            for row in ohlcv_rows
        ]
        # Exact only if 4h candles span (approximately) the whole horizon:
        # first candle at/near start and last candle near end. A 10-day
        # window at 4h is ~60 candles; require the last candle within one
        # 4h step of the horizon end, else the tail fell back to nothing.
        last_ts = candles[-1].timestamp
        covered = (end - last_ts) <= timedelta(hours=4)
        if covered:
            return candles, Fidelity.EXACT
        # Partial ohlcv coverage -> still usable, but the trade's fidelity
        # is the lowest available across its horizon: CLOSE_APPROX.
        return candles, Fidelity.CLOSE_APPROX

    # No ohlcv coverage at all -> market_snapshots close-only path.
    ms_resp = (
        client.table("market_snapshots")
        .select("snapshot_time, price_usd")
        .eq("asset_id", asset_id)
        .gte("snapshot_time", start_iso)
        .lte("snapshot_time", end_iso)
        .order("snapshot_time", desc=False)
        .execute()
    )
    ms_rows = cast(list[dict[str, Any]], ms_resp.data or [])
    candles = [
        ForwardCandle(
            timestamp=_parse_ts(str(row["snapshot_time"])),
            high=float(row["price_usd"]),
            low=float(row["price_usd"]),
            close=float(row["price_usd"]),
        )
        for row in ms_rows
    ]
    return candles, Fidelity.CLOSE_APPROX
