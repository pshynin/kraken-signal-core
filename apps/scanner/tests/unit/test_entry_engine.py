"""Unit tests for scanner.entry_engine — classify_setup + compute_entry_levels."""

from __future__ import annotations

import pytest

from scanner.entry_engine import (
    ANCHOR_20D_HIGH_TRIGGER,
    ANCHOR_ABOVE_20D_HIGH,
    ANCHOR_ATR,
    ANCHOR_EMA20,
    ANCHOR_EMA50,
    ANCHOR_VWAP,
    classify_setup,
    compute_entry_levels,
)
from scanner.models import (
    AssetIndicators,
    IndicatorSnapshot,
    MarketMetrics,
)
from scanner.selector import SelectorConfig

# ── Helpers ───────────────────────────────────────────────────────────────────

_CFG = SelectorConfig()


def _snap(
    trend_state: str | None = "up",
    ema_alignment: str | None = "bullish",
    vwap_state: str | None = "above",
    rsi_14: float | None = 60.0,
    atr_14_pct: float | None = 8.0,
    price_vs_ema20_pct: float | None = 3.0,
    ema_20: float | None = None,
    ema_50: float | None = None,
    vwap: float | None = None,
    volume_current: float | None = 1200.0,
    volume_ma_20: float | None = 1000.0,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="X",
        timeframe="4h",
        snapshot_time="",
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=None,
        price_vs_ema20_pct=price_vs_ema20_pct,
        price_vs_ema50_pct=None,
        price_vs_ema200_pct=None,
        vwap=vwap,
        price_vs_vwap_pct=None,
        rsi_14=rsi_14,
        atr_14=None,
        atr_14_pct=atr_14_pct,
        volume_ma_20=volume_ma_20,
        volume_current=volume_current,
        trend_state=trend_state,
        ema_alignment=ema_alignment,
        vwap_state=vwap_state,
    )


def _indicator(
    trend_state: str | None = "up",
    ema_alignment: str | None = "bullish",
    price_vs_ema20_pct: float | None = 3.0,
    ema_20: float | None = None,
    ema_50: float | None = None,
    vwap: float | None = None,
) -> AssetIndicators:
    s = _snap(
        trend_state=trend_state,
        ema_alignment=ema_alignment,
        price_vs_ema20_pct=price_vs_ema20_pct,
        ema_20=ema_20,
        ema_50=ema_50,
        vwap=vwap,
    )
    return AssetIndicators(symbol="X", kraken_pair="XUSD", tf_4h=s, tf_1h=s, tf_30m=s)


def _metrics(
    price_usd: float = 100.0,
    atr_pct_7d: float | None = 8.0,
    dist_from_20d_high: float | None = -0.15,
    return_7d: float | None = 0.12,
    return_3d: float | None = 0.06,
) -> MarketMetrics:
    return MarketMetrics(
        symbol="X",
        kraken_pair="XUSD",
        snapshot_time="",
        price_usd=price_usd,
        price_btc=None,
        atr_pct_7d=atr_pct_7d,
        dist_from_7d_high=None,
        dist_from_20d_high=dist_from_20d_high,
        return_3d=return_3d,
        return_7d=return_7d,
        return_14d=None,
        return_vs_btc_7d=None,
        volume_24h_usd=None,
        volume_7d_avg_usd=None,
        volume_ratio_20d=None,
        spread_pct=None,
    )


# ── classify_setup: pullback ──────────────────────────────────────────────────


def test_classify_default_is_pullback() -> None:
    assert classify_setup(_metrics(), _indicator()) == "pullback"


def test_classify_pullback_when_far_from_high() -> None:
    m = _metrics(dist_from_20d_high=-0.20, return_7d=0.05)
    ind = _indicator(price_vs_ema20_pct=10.0)  # too far above EMA-20 for reclaim
    assert classify_setup(m, ind) == "pullback"


def test_classify_pullback_when_return_7d_is_none() -> None:
    m = _metrics(return_7d=None, dist_from_20d_high=-0.02)
    assert classify_setup(m, _indicator()) == "pullback"


# ── classify_setup: breakout_trigger ─────────────────────────────────────────


def test_classify_breakout_near_high_strong_return() -> None:
    m = _metrics(dist_from_20d_high=-0.02, return_7d=0.12)
    assert classify_setup(m, _indicator()) == "breakout_trigger"


def test_classify_breakout_at_exactly_minus3pct() -> None:
    m = _metrics(dist_from_20d_high=-0.03, return_7d=0.09)
    assert classify_setup(m, _indicator()) == "breakout_trigger"


def test_classify_not_breakout_if_weak_return() -> None:
    m = _metrics(dist_from_20d_high=-0.02, return_7d=0.08)  # exactly 8 % — not >
    assert classify_setup(m, _indicator()) != "breakout_trigger"


def test_classify_not_breakout_if_trend_down() -> None:
    m = _metrics(dist_from_20d_high=-0.02, return_7d=0.15)
    ind = _indicator(trend_state="down")
    assert classify_setup(m, ind) != "breakout_trigger"


def test_classify_breakout_priority_over_reclaim() -> None:
    # Conditions that could match reclaim also match breakout → breakout wins.
    m = _metrics(dist_from_20d_high=-0.02, return_7d=0.12, return_3d=0.02)
    ind = _indicator(price_vs_ema20_pct=2.0)  # within reclaim range too
    assert classify_setup(m, ind) == "breakout_trigger"


# ── classify_setup: reclaim ───────────────────────────────────────────────────


def test_classify_reclaim_at_ema20() -> None:
    m = _metrics(dist_from_20d_high=-0.10, return_7d=0.05, return_3d=0.02)
    ind = _indicator(price_vs_ema20_pct=1.5)
    assert classify_setup(m, ind) == "reclaim"


def test_classify_reclaim_with_negative_ema20_pct() -> None:
    m = _metrics(dist_from_20d_high=-0.10, return_7d=-0.02, return_3d=0.01)
    ind = _indicator(price_vs_ema20_pct=-2.5, trend_state="neutral")
    assert classify_setup(m, ind) == "reclaim"


def test_classify_not_reclaim_if_return_7d_too_high() -> None:
    m = _metrics(dist_from_20d_high=-0.10, return_7d=0.10, return_3d=0.03)
    ind = _indicator(price_vs_ema20_pct=1.5)
    assert classify_setup(m, ind) != "reclaim"


def test_classify_not_reclaim_if_negative_3d_return() -> None:
    m = _metrics(dist_from_20d_high=-0.10, return_7d=0.04, return_3d=-0.01)
    ind = _indicator(price_vs_ema20_pct=1.5)
    assert classify_setup(m, ind) != "reclaim"


def test_classify_not_reclaim_if_ema20_pct_too_high() -> None:
    m = _metrics(dist_from_20d_high=-0.10, return_7d=0.04, return_3d=0.02)
    ind = _indicator(price_vs_ema20_pct=6.0)  # too far above EMA-20
    assert classify_setup(m, ind) != "reclaim"


# ── compute_entry_levels: pullback ────────────────────────────────────────────


def test_pullback_preferred_always_below_price() -> None:
    levels = compute_entry_levels("pullback", _metrics(), _indicator(), _CFG)
    assert levels.preferred_entry < 100.0


def test_pullback_max_entry_above_preferred() -> None:
    levels = compute_entry_levels("pullback", _metrics(), _indicator(), _CFG)
    assert levels.max_entry > levels.preferred_entry


def test_pullback_uses_ema20_when_qualified() -> None:
    ind = _indicator(ema_20=94.0)  # 6 % below price — qualifies
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_EMA20
    assert levels.preferred_entry == pytest.approx(94.0 * 1.0025)


def test_pullback_uses_ema50_when_ema20_absent() -> None:
    ind = _indicator(ema_50=90.0)
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_EMA50
    assert levels.preferred_entry == pytest.approx(90.0 * 1.0025)


def test_pullback_picks_highest_qualified_support() -> None:
    ind = _indicator(ema_20=94.0, ema_50=88.0)  # ema_20 is higher → preferred
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_EMA20
    assert levels.preferred_entry == pytest.approx(94.0 * 1.0025)


def test_pullback_ignores_support_within_min_discount() -> None:
    ind = _indicator(ema_20=99.0)  # only 1 % below — below 2 % min discount
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_ATR


def test_pullback_atr_fallback_min_three_pct() -> None:
    ind = _indicator()  # no support levels
    levels = compute_entry_levels("pullback", _metrics(atr_pct_7d=0.1), ind, _CFG)
    assert levels.preferred_entry == pytest.approx(100.0 * 0.97)  # 3 % floor
    assert levels.support_anchor_type == ANCHOR_ATR
    assert levels.support_anchor_value is None


def test_pullback_atr_fallback_uses_atr_when_deep_enough() -> None:
    ind = _indicator()  # no support
    levels = compute_entry_levels("pullback", _metrics(atr_pct_7d=10.0), ind, _CFG)
    assert levels.preferred_entry == pytest.approx(100.0 * (1 - 0.10))  # 10 % ATR × 1.0


def test_pullback_uses_vwap_anchor() -> None:
    ind = _indicator(vwap=92.0)  # 8 % below → qualifies
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_VWAP
    assert levels.preferred_entry == pytest.approx(92.0 * 1.0025)


# ── compute_entry_levels: breakout_trigger ────────────────────────────────────


def test_breakout_anchor_type_trigger_when_below_high() -> None:
    m = _metrics(dist_from_20d_high=-0.02, price_usd=100.0)  # 2 % below high
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.support_anchor_type == ANCHOR_20D_HIGH_TRIGGER


def test_breakout_preferred_above_20d_high() -> None:
    m = _metrics(dist_from_20d_high=-0.02, price_usd=100.0)
    # 20d_high = 100 / 0.98 ≈ 102.04
    twenty_d_high = 100.0 / (1.0 - 0.02)
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.preferred_entry == pytest.approx(twenty_d_high * 1.002, rel=1e-5)


def test_breakout_max_entry_caps_chase() -> None:
    m = _metrics(dist_from_20d_high=-0.02, price_usd=100.0)
    twenty_d_high = 100.0 / 0.98
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.max_entry == pytest.approx(twenty_d_high * 1.015, rel=1e-5)


def test_breakout_above_high_uses_above_20d_high_anchor() -> None:
    m = _metrics(dist_from_20d_high=-0.01, price_usd=100.0)  # within 1.5 %
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.support_anchor_type == ANCHOR_ABOVE_20D_HIGH


def test_breakout_preferred_entry_can_exceed_current_price() -> None:
    m = _metrics(dist_from_20d_high=-0.02, price_usd=100.0)
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.preferred_entry > 100.0


def test_breakout_raises_when_dist_from_20d_high_is_none() -> None:
    m = _metrics(dist_from_20d_high=None)
    with pytest.raises(ValueError, match="dist_from_20d_high"):
        compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)


# ── compute_entry_levels: reclaim ─────────────────────────────────────────────


def test_reclaim_uses_ema20_anchor() -> None:
    ind = _indicator(ema_20=97.0)  # 3 % below price — within [0.1 %, 4 %]
    levels = compute_entry_levels("reclaim", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_EMA20
    assert levels.preferred_entry == pytest.approx(97.0 * 1.0025)


def test_reclaim_preferred_below_current_price() -> None:
    ind = _indicator(ema_20=97.0)
    levels = compute_entry_levels("reclaim", _metrics(), ind, _CFG)
    assert levels.preferred_entry < 100.0


def test_reclaim_max_entry_above_preferred() -> None:
    ind = _indicator(ema_20=97.0)
    levels = compute_entry_levels("reclaim", _metrics(), ind, _CFG)
    assert levels.max_entry > levels.preferred_entry


def test_reclaim_max_entry_anchored_to_reclaim_level() -> None:
    ind = _indicator(ema_20=97.0)
    levels = compute_entry_levels("reclaim", _metrics(), ind, _CFG)
    assert levels.max_entry == pytest.approx(97.0 * (1.0 + _CFG.max_chase_reclaim), rel=1e-5)


def test_reclaim_raises_when_no_anchor_in_range() -> None:
    ind = _indicator()  # ema_20=None, vwap=None — no levels in range
    with pytest.raises(ValueError, match="no level"):
        compute_entry_levels("reclaim", _metrics(), ind, _CFG)


def test_reclaim_raises_when_level_too_far_below() -> None:
    ind = _indicator(ema_20=90.0)  # 10 % below — exceeds 4 % max proximity
    with pytest.raises(ValueError, match="no level"):
        compute_entry_levels("reclaim", _metrics(), ind, _CFG)


def test_reclaim_raises_when_level_too_close() -> None:
    ind = _indicator(ema_20=99.99)  # < 0.1 % below — within min proximity buffer
    with pytest.raises(ValueError, match="no level"):
        compute_entry_levels("reclaim", _metrics(), ind, _CFG)


def test_reclaim_picks_highest_near_level() -> None:
    ind = _indicator(ema_20=97.0, vwap=96.0)  # ema_20 is higher
    levels = compute_entry_levels("reclaim", _metrics(), ind, _CFG)
    assert levels.support_anchor_type == ANCHOR_EMA20


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_breakout_anchor_value_is_20d_high() -> None:
    m = _metrics(dist_from_20d_high=-0.02, price_usd=100.0)
    twenty_d_high = round(100.0 / 0.98, 8)
    levels = compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert levels.support_anchor_value == pytest.approx(twenty_d_high, rel=1e-5)


def test_pullback_anchor_value_is_ema_price() -> None:
    ind = _indicator(ema_20=94.0)
    levels = compute_entry_levels("pullback", _metrics(), ind, _CFG)
    assert levels.support_anchor_value == pytest.approx(94.0)


def test_pullback_entry_levels_are_frozen() -> None:
    levels = compute_entry_levels("pullback", _metrics(), _indicator(), _CFG)
    with pytest.raises(Exception):
        levels.preferred_entry = 0.0  # type: ignore[misc]


def test_unknown_setup_type_defaults_to_pullback_logic() -> None:
    levels = compute_entry_levels("unknown_type", _metrics(), _indicator(), _CFG)
    assert levels.preferred_entry < 100.0


# ── EntryEngineError + rejection-reason constants ─────────────────────────────


def test_breakout_missing_dist_raises_typed_error_with_reason() -> None:
    """Breakout setup with no dist_from_20d_high raises EntryEngineError carrying
    the ENTRY_REJECT_MISSING_DIST_20D constant."""
    from scanner.entry_engine import EntryEngineError
    from scanner.rejection_reasons import ENTRY_REJECT_MISSING_DIST_20D

    m = _metrics(dist_from_20d_high=None, price_usd=100.0)
    with pytest.raises(EntryEngineError) as exc:
        compute_entry_levels("breakout_trigger", m, _indicator(), _CFG)
    assert exc.value.reason == ENTRY_REJECT_MISSING_DIST_20D


def test_reclaim_no_anchor_raises_typed_error_with_reason() -> None:
    """Reclaim setup with no qualifying anchor raises EntryEngineError carrying
    the ENTRY_REJECT_NO_QUALIFIED_ANCHOR constant."""
    from scanner.entry_engine import EntryEngineError
    from scanner.rejection_reasons import ENTRY_REJECT_NO_QUALIFIED_ANCHOR

    # Reclaim requires an EMA-20 or VWAP within [-4%, -0.1%] of price.
    # Provide both as None so no anchor qualifies.
    ind = _indicator(ema_20=None, vwap=None)
    with pytest.raises(EntryEngineError) as exc:
        compute_entry_levels("reclaim", _metrics(price_usd=100.0), ind, _CFG)
    assert exc.value.reason == ENTRY_REJECT_NO_QUALIFIED_ANCHOR


def test_entry_engine_error_is_value_error_subclass() -> None:
    """EntryEngineError preserves ValueError compatibility for legacy callers."""
    from scanner.entry_engine import EntryEngineError
    from scanner.rejection_reasons import ENTRY_REJECT_UNKNOWN

    err = EntryEngineError(ENTRY_REJECT_UNKNOWN, "something went wrong")
    assert isinstance(err, ValueError)
    assert err.reason == ENTRY_REJECT_UNKNOWN


def test_entry_engine_error_default_message_is_reason() -> None:
    """When no explicit message is provided, str(exc) == reason."""
    from scanner.entry_engine import EntryEngineError
    from scanner.rejection_reasons import ENTRY_REJECT_UNKNOWN

    err = EntryEngineError(ENTRY_REJECT_UNKNOWN)
    assert str(err) == ENTRY_REJECT_UNKNOWN
