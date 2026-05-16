"""Unit tests for scanner.validation (PR H2 + PR I).

PR H2: the pure core (compute_outcome) tested with synthetic price paths.
PR I:  aggregation/formatting (pure), the two DB fetchers (mocked
       Supabase client), and a CLI smoke test over a fixture dataset.
No real DB, no network anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from scanner.validation import (
    Fidelity,
    ForwardCandle,
    OutcomeKind,
    TradeOutcome,
    TradeSpec,
    aggregate_outcomes,
    compute_outcome,
    fetch_forward_path,
    fetch_trade_specs,
    format_report,
    run_report,
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
        asset_id="asset-btc",
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


# ── PR I: aggregation (pure) ──────────────────────────────────────────────────


def _outcome(
    *,
    kind: OutcomeKind,
    fidelity: Fidelity = Fidelity.EXACT,
    setup: str | None = "pullback",
    category: str = "clean",
    size: str = "5k-10k",
    prob: float | None = 77.0,
    filled: bool = True,
    ret: float | None = 0.1,
    mae: float | None = -0.05,
    mfe: float | None = 0.2,
) -> TradeOutcome:
    return TradeOutcome(
        symbol="X",
        scan_run_id="r",
        category=category,
        setup_type=setup,
        size_bucket=size,
        probability_pct=prob,
        kind=kind,
        fidelity=fidelity,
        filled=filled,
        fill_time=None,
        exit_time=None,
        days_to_fill=None,
        days_to_exit=None,
        realized_return=ret,
        mae=mae,
        mfe=mfe,
    )


def test_aggregate_splits_by_fidelity_exact_first() -> None:
    outs = [
        _outcome(kind=OutcomeKind.TARGET_HIT, fidelity=Fidelity.CLOSE_APPROX),
        _outcome(kind=OutcomeKind.STOP_HIT, fidelity=Fidelity.EXACT),
    ]
    reps = aggregate_outcomes(outs)
    assert [r.fidelity for r in reps] == [Fidelity.EXACT, Fidelity.CLOSE_APPROX]


def test_aggregate_skips_empty_fidelity_cohort() -> None:
    outs = [_outcome(kind=OutcomeKind.TARGET_HIT, fidelity=Fidelity.EXACT)]
    reps = aggregate_outcomes(outs)
    assert len(reps) == 1
    assert reps[0].fidelity is Fidelity.EXACT


def test_cohort_rates_are_over_filled_not_total() -> None:
    # 4 trades: 1 no_fill, 2 target, 1 stop. fill_rate = 3/4.
    # target_rate/stop_rate are over the 3 filled, not 4.
    outs = [
        _outcome(kind=OutcomeKind.NO_FILL, filled=False, ret=None, mae=None, mfe=None),
        _outcome(kind=OutcomeKind.TARGET_HIT),
        _outcome(kind=OutcomeKind.TARGET_HIT),
        _outcome(kind=OutcomeKind.STOP_HIT),
    ]
    rep = aggregate_outcomes(outs)[0]
    assert rep.overall.n == 4
    assert rep.overall.n_filled == 3
    assert rep.overall.fill_rate == 0.75
    assert rep.overall.target_rate == round(2 / 3, 6)
    assert rep.overall.stop_rate == round(1 / 3, 6)


def test_cohort_rates_zero_when_no_fills() -> None:
    outs = [_outcome(kind=OutcomeKind.NO_FILL, filled=False, ret=None, mae=None, mfe=None)]
    rep = aggregate_outcomes(outs)[0]
    assert rep.overall.fill_rate == 0.0
    assert rep.overall.target_rate == 0.0
    assert rep.overall.avg_realized_return is None


def test_breakdown_dimensions_present_and_sorted() -> None:
    outs = [
        _outcome(kind=OutcomeKind.TARGET_HIT, setup="pullback", category="clean"),
        _outcome(kind=OutcomeKind.STOP_HIT, setup="breakout_trigger", category="ugly"),
    ]
    rep = aggregate_outcomes(outs)[0]
    setups = [c.label for c in rep.by_setup]
    assert setups == sorted(setups)
    assert set(setups) == {"pullback", "breakout_trigger"}
    assert {c.label for c in rep.by_category} == {"clean", "ugly"}


def test_breakdown_handles_null_setup_type() -> None:
    outs = [_outcome(kind=OutcomeKind.TARGET_HIT, setup=None)]
    rep = aggregate_outcomes(outs)[0]
    assert any(c.label == "unknown" for c in rep.by_setup)


def test_prob_tier_bucketing() -> None:
    outs = [
        _outcome(kind=OutcomeKind.TARGET_HIT, prob=92.0),
        _outcome(kind=OutcomeKind.TARGET_HIT, prob=77.0),
        _outcome(kind=OutcomeKind.TARGET_HIT, prob=None),
    ]
    rep = aggregate_outcomes(outs)[0]
    tiers = {c.label for c in rep.by_prob_tier}
    assert ">=90" in tiers
    assert "77-83" in tiers
    assert "none" in tiers


# ── PR I: report formatting (pure) ────────────────────────────────────────────


def test_format_report_empty() -> None:
    assert "No trade outcomes" in format_report([])


def test_format_report_has_both_fidelity_sections() -> None:
    outs = [
        _outcome(kind=OutcomeKind.TARGET_HIT, fidelity=Fidelity.EXACT),
        _outcome(kind=OutcomeKind.STOP_HIT, fidelity=Fidelity.CLOSE_APPROX),
    ]
    text = format_report(aggregate_outcomes(outs))
    assert "Fidelity: EXACT" in text
    assert "Fidelity: CLOSE_APPROX" in text
    # The approx section carries the lower-bound caveat.
    assert "lower bound" in text


def test_format_report_includes_breakdown_titles() -> None:
    outs = [_outcome(kind=OutcomeKind.TARGET_HIT)]
    text = format_report(aggregate_outcomes(outs))
    for title in (
        "Overall",
        "By setup type",
        "By category",
        "By size bucket",
        "By probability tier",
    ):
        assert title in text


# ── PR I: DB fetchers (mocked Supabase client) ────────────────────────────────


def _spec_row(**over: object) -> dict:
    base = {
        "category": "clean",
        "setup_type": "pullback",
        "preferred_entry": 100.0,
        "max_entry": 102.0,
        "entry_price": 100.0,
        "exit_price": 130.0,
        "stop_loss": 90.0,
        "probability_pct": 77.0,
        "suggested_size_bucket": "5k-10k",
        "scan_run_id": "run-1",
        "asset_id": "asset-btc",
        "assets": {"symbol": "BTC"},
        "scan_runs": {"started_at": "2026-01-01T00:00:00+00:00"},
    }
    base.update(over)
    return base


def test_fetch_trade_specs_maps_row_to_spec() -> None:
    client = MagicMock()
    resp = MagicMock()
    resp.data = [_spec_row()]
    client.table.return_value.select.return_value.execute.return_value = resp

    specs = fetch_trade_specs(client)
    assert len(specs) == 1
    s = specs[0]
    assert s.symbol == "BTC"
    assert s.asset_id == "asset-btc"
    assert s.setup_type == "pullback"
    assert s.preferred_entry == 100.0
    assert s.max_entry == 102.0


def test_fetch_trade_specs_falls_back_to_entry_price() -> None:
    client = MagicMock()
    resp = MagicMock()
    # Older row: no preferred_entry / max_entry columns populated.
    resp.data = [_spec_row(preferred_entry=None, max_entry=None, entry_price=55.0)]
    client.table.return_value.select.return_value.execute.return_value = resp

    s = fetch_trade_specs(client)[0]
    assert s.preferred_entry == 55.0
    assert s.max_entry == 55.0


def test_fetch_trade_specs_since_filter() -> None:
    client = MagicMock()
    resp = MagicMock()
    resp.data = [
        _spec_row(scan_runs={"started_at": "2026-01-01T00:00:00+00:00"}),
        _spec_row(scan_runs={"started_at": "2026-03-01T00:00:00+00:00"}),
    ]
    client.table.return_value.select.return_value.execute.return_value = resp

    specs = fetch_trade_specs(client, since=datetime(2026, 2, 1, tzinfo=UTC))
    assert len(specs) == 1
    assert specs[0].scan_time == datetime(2026, 3, 1, tzinfo=UTC)


def _ohlcv_chain(client: MagicMock, rows: list[dict]) -> None:
    """Wire client.table('ohlcv_candles').select()...execute() -> rows."""
    resp = MagicMock()
    resp.data = rows
    (
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value
    ) = resp


def test_fetch_forward_path_exact_when_ohlcv_covers_horizon() -> None:
    client = MagicMock()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # Last candle within 4h of horizon end (start + 10d) -> EXACT.
    rows = [
        {
            "candle_timestamp": "2026-01-01T00:00:00+00:00",
            "high": 101,
            "low": 99,
            "close": 100,
        },
        {
            "candle_timestamp": "2026-01-10T22:00:00+00:00",
            "high": 110,
            "low": 105,
            "close": 108,
        },
    ]
    _ohlcv_chain(client, rows)
    candles, fidelity = fetch_forward_path(client, "BTC", "asset-btc", start)
    assert fidelity is Fidelity.EXACT
    assert len(candles) == 2


def test_fetch_forward_path_falls_back_to_market_snapshots() -> None:
    client = MagicMock()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    _ohlcv_chain(client, [])  # no ohlcv coverage

    ms_resp = MagicMock()
    ms_resp.data = [{"snapshot_time": "2026-01-02T00:00:00+00:00", "price_usd": 100.0}]
    (
        client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value
    ) = ms_resp

    candles, fidelity = fetch_forward_path(client, "BTC", "asset-btc", start)
    assert fidelity is Fidelity.CLOSE_APPROX
    assert len(candles) == 1
    # market_snapshots path: high == low == close.
    assert candles[0].high == candles[0].low == candles[0].close == 100.0


# ── PR I: CLI smoke (run_report end to end over a mocked client) ──────────────


def test_run_report_end_to_end_smoke() -> None:
    """run_report wires fetch_trade_specs + fetch_forward_path +
    compute_outcome + aggregate + format. One TARGET_HIT trade with exact
    OHLCV coverage should surface in an EXACT section."""
    client = MagicMock()

    specs_resp = MagicMock()
    specs_resp.data = [_spec_row()]
    client.table.return_value.select.return_value.execute.return_value = specs_resp

    # ohlcv covering the horizon, price runs from entry up through target.
    ohlcv = [
        {"candle_timestamp": "2026-01-01T00:00:00+00:00", "high": 101, "low": 99, "close": 100},
        {"candle_timestamp": "2026-01-03T00:00:00+00:00", "high": 135, "low": 100, "close": 132},
        {"candle_timestamp": "2026-01-10T22:00:00+00:00", "high": 133, "low": 128, "close": 130},
    ]
    _ohlcv_chain(client, ohlcv)

    text = run_report(client)
    assert "Fidelity: EXACT" in text
    assert "Overall" in text
    # One filled target-hit trade -> fill 100%, and a positive avg return.
    assert "fill=100%" in text
