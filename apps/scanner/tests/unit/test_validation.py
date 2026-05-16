"""Unit tests for scanner.validation — trade outcome computation (PR H2).

The pure core (compute_outcome) is tested exhaustively with synthetic
forward price paths. No DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scanner.validation import (
    Fidelity,
    ForwardCandle,
    OutcomeKind,
    TradeSpec,
    compute_outcome,
)

_SCAN_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def _spec(
    preferred: float = 100.0,
    max_entry: float = 102.0,
    exit_price: float = 130.0,
    stop_loss: float = 90.0,
) -> TradeSpec:
    return TradeSpec(
        symbol="BTC",
        scan_run_id="run-1",
        category="clean",
        setup_type="pullback",
        scan_time=_SCAN_TIME,
        preferred_entry=preferred,
        max_entry=max_entry,
        exit_price=exit_price,
        stop_loss=stop_loss,
        probability_pct=77.0,
        size_bucket="5k-10k",
    )


def _c(day: float, high: float, low: float, close: float) -> ForwardCandle:
    return ForwardCandle(
        timestamp=_SCAN_TIME + timedelta(days=day),
        high=high,
        low=low,
        close=close,
    )


# ── No fill ───────────────────────────────────────────────────────────────────


def test_no_fill_when_zone_never_reached() -> None:
    # Price stays above max_entry (102) the whole horizon.
    path = [_c(d, high=120, low=110, close=115) for d in (1, 2, 3, 5, 8)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.NO_FILL
    assert out.filled is False
    assert out.realized_return is None
    assert out.mae is None and out.mfe is None


def test_no_fill_when_zone_reached_after_horizon() -> None:
    # Touches the zone only on day 12 — past the 10-day horizon.
    path = [_c(1, 120, 110, 115), _c(12, 101, 99, 100)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.NO_FILL


# ── Fill semantics ────────────────────────────────────────────────────────────


def test_fill_at_preferred_when_price_trades_through_it() -> None:
    # Day 1 low (95) <= preferred (100): filled at preferred.
    path = [_c(1, 103, 95, 100), _c(2, 135, 100, 132)]  # day 2 hits target
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.filled is True
    assert out.kind is OutcomeKind.TARGET_HIT
    # realized from preferred=100 to exit=130 -> +0.30
    assert out.realized_return == 0.3


def test_fill_on_chase_at_max_entry_when_preferred_not_touched() -> None:
    # Zone entered (low 101 <= max_entry 102) but never down to preferred 100.
    # Fill price = min(max_entry, candle high). high=101.5 -> fill 101.5.
    path = [_c(1, 101.5, 101, 101.2), _c(2, 135, 120, 132)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.filled is True
    # realized from fill 101.5 to exit 130
    assert out.realized_return == round((130 - 101.5) / 101.5, 6)


# ── Target / stop ─────────────────────────────────────────────────────────────


def test_target_hit() -> None:
    path = [_c(1, 101, 99, 100), _c(3, 131, 105, 129)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.TARGET_HIT
    assert out.realized_return == 0.3
    assert out.days_to_exit is not None


def test_stop_hit() -> None:
    path = [_c(1, 101, 99, 100), _c(2, 100, 88, 91)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.STOP_HIT
    # realized from fill 100 to stop 90 -> -0.10
    assert out.realized_return == -0.1


def test_same_candle_stop_and_target_counts_stop_first() -> None:
    # Day 2 candle spans BOTH stop (90) and target (130). Locked: stop first.
    path = [_c(1, 101, 99, 100), _c(2, 135, 85, 110)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.STOP_HIT
    assert out.realized_return == -0.1


# ── Expiry ────────────────────────────────────────────────────────────────────


def test_expired_open_marked_to_last_close() -> None:
    # Fills day 1, never hits stop/target, drifts to 118 by the last
    # in-horizon candle (day 8).
    path = [_c(1, 101, 99, 100), _c(4, 120, 100, 112), _c(8, 125, 110, 118)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.EXPIRED_OPEN
    assert out.exit_time is None
    assert out.days_to_exit is None
    # marked to last close 118 from fill 100 -> +0.18
    assert out.realized_return == 0.18


def test_candles_past_horizon_are_ignored_for_resolution() -> None:
    # Target only reached on day 11 — past horizon. Must expire, not target.
    path = [_c(1, 101, 99, 100), _c(8, 120, 110, 115), _c(11, 140, 130, 138)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.EXPIRED_OPEN
    assert out.realized_return == round((115 - 100) / 100, 6)


# ── MAE / MFE ─────────────────────────────────────────────────────────────────


def test_mae_mfe_measured_from_fill_price() -> None:
    # Fill at 100. Dips to 94 (MAE -6%), peaks at 122 (MFE +22%), expires.
    path = [
        _c(1, 101, 99, 100),
        _c(3, 105, 94, 98),
        _c(6, 122, 110, 120),
        _c(9, 121, 115, 118),
    ]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.kind is OutcomeKind.EXPIRED_OPEN
    assert out.mae == round((94 - 100) / 100, 6)
    assert out.mfe == round((122 - 100) / 100, 6)


def test_mae_mfe_none_when_not_filled() -> None:
    path = [_c(1, 200, 150, 175)]
    out = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert out.filled is False
    assert out.mae is None and out.mfe is None


# ── Fidelity passthrough ──────────────────────────────────────────────────────


def test_fidelity_is_recorded_on_the_outcome() -> None:
    path = [_c(1, 101, 99, 100), _c(2, 135, 120, 132)]
    out_exact = compute_outcome(_spec(), path, Fidelity.EXACT)
    out_approx = compute_outcome(_spec(), path, Fidelity.CLOSE_APPROX)
    assert out_exact.fidelity is Fidelity.EXACT
    assert out_approx.fidelity is Fidelity.CLOSE_APPROX


def test_close_approx_path_degenerate_high_low_still_resolves() -> None:
    # market_snapshots path: high == low == close. Stop detection works
    # only when the close itself crosses the level.
    path = [
        ForwardCandle(_SCAN_TIME + timedelta(days=1), 100, 100, 100),  # fill
        ForwardCandle(_SCAN_TIME + timedelta(days=3), 89, 89, 89),  # close < stop
    ]
    out = compute_outcome(_spec(), path, Fidelity.CLOSE_APPROX)
    assert out.kind is OutcomeKind.STOP_HIT
    assert out.fidelity is Fidelity.CLOSE_APPROX


# ── Determinism ───────────────────────────────────────────────────────────────


def test_compute_outcome_is_deterministic() -> None:
    path = [_c(1, 101, 95, 100), _c(2, 110, 98, 105), _c(5, 131, 120, 129)]
    a = compute_outcome(_spec(), path, Fidelity.EXACT)
    b = compute_outcome(_spec(), path, Fidelity.EXACT)
    assert a == b
