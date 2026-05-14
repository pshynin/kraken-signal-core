"""Entry Engine — PR entry-engine.

Classifies each scored candidate into a setup type and computes
deterministic entry levels (preferred_entry, max_entry) anchored
to structural support or trigger levels.

Public API (also exposed for unit testing):
    classify_setup(metrics, indicator)                           -> str
    compute_entry_levels(setup_type, metrics, indicator, config) -> EntryLevels

Setup types
───────────
pullback
    Buy a retracement in an established 4h uptrend.
    Anchor = highest of (EMA-20, EMA-50, VWAP on tf_4h) that is at least
    min_pullback_discount below current price.
    Fallback = ATR-based pullback (at least 3 % below market).
    preferred_entry is always strictly below current market price.

breakout_trigger
    Enter at or just above the 20-day rolling high.
    The only setup where preferred_entry may exceed current market price
    (price approaching the high from below, order triggers on the break).
    Max-entry caps the chase at max_chase_breakout above the 20d high.

reclaim
    Price has just re-crossed above a key level (EMA-20 or VWAP on tf_4h).
    Entry is just above the reclaimed level; stop is placed below it.
    preferred_entry is always strictly below current market price
    (the reclaim anchor must be within [4 %, 0.1 %] below price).

EntryConfig protocol
────────────────────
Functions accept any object whose attributes satisfy EntryConfig.
scanner.selector.SelectorConfig implicitly satisfies this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scanner.models import AssetIndicators, MarketMetrics
from scanner.rejection_reasons import (
    ENTRY_REJECT_MISSING_DIST_20D,
    ENTRY_REJECT_NO_QUALIFIED_ANCHOR,
)


class EntryEngineError(ValueError):
    """Raised when the entry engine cannot produce a valid trade plan.

    Carries a `reason` field set to one of the constants in
    `scanner.rejection_reasons`. The selector catches this exception and
    records an `EntryRejection`; other exceptions propagate.

    Subclasses `ValueError` so existing callers that catch `ValueError`
    continue to work, but new code should narrow to this class to avoid
    swallowing genuine bugs.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


# ── EntryConfig protocol ──────────────────────────────────────────────────────


class EntryConfig(Protocol):
    """Structural protocol — any config object with these attributes works.

    Declared as @property so frozen dataclasses (which expose read-only
    attributes) satisfy the protocol under strict mypy checking.
    """

    @property
    def min_pullback_discount(self) -> float: ...

    """Min fractional discount a support level must offer to qualify (e.g. 0.02 = 2 %)."""

    @property
    def max_pullback_depth(self) -> float: ...

    """Max fractional distance below market before a pullback entry is deemed unreachable."""

    @property
    def max_chase_pullback(self) -> float: ...

    """max_entry margin above preferred_entry for pullback setups (e.g. 0.01 = 1 %)."""

    @property
    def max_chase_breakout(self) -> float: ...

    """max_entry margin above the 20d high for breakout setups (e.g. 0.015 = 1.5 %)."""

    @property
    def max_chase_reclaim(self) -> float: ...

    """max_entry margin above the reclaim anchor (e.g. 0.02 = 2 %)."""

    @property
    def max_chase_current_price_pct(self) -> float: ...

    """Breakout only: max preferred_entry above current price before rejecting chase."""


# ── EntryLevels ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntryLevels:
    """Entry level pair returned by compute_entry_levels().

    preferred_entry      — ideal limit order price; place the buy order here.
    max_entry            — chase ceiling; do not buy above this price.
    support_anchor_type  — label for the structural level used as anchor.
    support_anchor_value — raw price of the anchor (None for atr_fallback).
    """

    preferred_entry: float
    max_entry: float
    support_anchor_type: str
    support_anchor_value: float | None


# Anchor type string constants (also stored in DB support_anchor_type column).
ANCHOR_EMA20 = "ema_20"
ANCHOR_EMA50 = "ema_50"
ANCHOR_VWAP = "vwap"
ANCHOR_ATR = "atr_fallback"
ANCHOR_20D_HIGH_TRIGGER = "20d_high_trigger"
ANCHOR_ABOVE_20D_HIGH = "above_20d_high"

# ── Setup classification constants ────────────────────────────────────────────

_BRK_MIN_DIST_20D_HIGH: float = -0.03  # within 3 % of 20d high → breakout candidate
_BRK_MIN_RETURN_7D: float = 0.08  # requires ≥ +8 % 7-day return

_RCL_EMA20_PCT_MIN: float = -3.0  # price_vs_ema20_pct lower bound (%)
_RCL_EMA20_PCT_MAX: float = 4.0  # price_vs_ema20_pct upper bound (%)
_RCL_RETURN_3D_MIN: float = 0.0  # must show positive 3-day return
_RCL_RETURN_7D_MIN: float = -0.12  # 7-day return floor
_RCL_RETURN_7D_MAX: float = 0.08  # 7-day return ceiling (above = breakout territory)

# ── Entry computation constants ───────────────────────────────────────────────

_PULLBACK_FILL_BUFFER: float = 0.0025  # 0.25 % above anchor for order fill headroom
_PULLBACK_ATR_MULT: float = 1.0  # ATR × this = fallback pullback depth
_PULLBACK_ATR_MIN: float = 0.03  # ATR fallback floor: at least 3 % below market

_RECLAIM_MAX_PROXIMITY: float = 0.04  # anchor must be ≤ 4 % below current price
_RECLAIM_MIN_PROXIMITY: float = 0.001  # anchor must be ≥ 0.1 % below current price
_RECLAIM_FILL_BUFFER: float = 0.0025  # 0.25 % above anchor for fill headroom

_BREAKOUT_TRIGGER_BUFFER: float = 0.002  # 0.2 % above 20d high when approaching
_BREAKOUT_AT_HIGH_BUFFER: float = 0.001  # 0.1 % below current price when already above high


# ── classify_setup ────────────────────────────────────────────────────────────


def classify_setup(
    metrics: MarketMetrics,
    indicator: AssetIndicators,
) -> str:
    """Classify one candidate into a setup type.

    Evaluation order (first match wins):
        1. breakout_trigger — near the 20d high with strong recent momentum
        2. reclaim          — price just re-crossed EMA-20 with positive momentum
        3. pullback         — default for uptrend candidates

    Returns:
        'pullback' | 'breakout_trigger' | 'reclaim'
    """
    snap = indicator.tf_4h
    dist = metrics.dist_from_20d_high
    ret7d = metrics.return_7d
    ret3d = metrics.return_3d

    # 1. Breakout-trigger: within 3 % of 20d high + strong 7d momentum
    if (
        dist is not None
        and dist >= _BRK_MIN_DIST_20D_HIGH
        and ret7d is not None
        and ret7d > _BRK_MIN_RETURN_7D
        and snap.trend_state in {"up", "strong_up"}
    ):
        return "breakout_trigger"

    # 2. Reclaim: EMA-20 within ±3–4 % of price and positive short-term momentum
    if (
        snap.price_vs_ema20_pct is not None
        and _RCL_EMA20_PCT_MIN <= snap.price_vs_ema20_pct <= _RCL_EMA20_PCT_MAX
        and ret3d is not None
        and ret3d > _RCL_RETURN_3D_MIN
        and ret7d is not None
        and _RCL_RETURN_7D_MIN <= ret7d <= _RCL_RETURN_7D_MAX
        and snap.trend_state in {"up", "neutral"}
    ):
        return "reclaim"

    # 3. Default
    return "pullback"


# ── compute_entry_levels ──────────────────────────────────────────────────────


def compute_entry_levels(
    setup_type: str,
    metrics: MarketMetrics,
    indicator: AssetIndicators,
    config: EntryConfig,
) -> EntryLevels:
    """Compute preferred_entry and max_entry for the given setup type.

    Raises:
        ValueError: if the setup cannot produce valid entry levels
                    (missing data, no identifiable anchor, invalid structure).
                    Callers (run_candidate_selector._build) catch this and drop
                    the candidate, logging a warning.
    """
    price = metrics.price_usd
    atr_pct = metrics.atr_pct_7d

    if setup_type == "breakout_trigger":
        return _breakout_entry_levels(metrics.symbol, price, metrics, config)
    if setup_type == "reclaim":
        return _reclaim_entry_levels(metrics.symbol, price, indicator, config)
    return _pullback_entry_levels(price, indicator, atr_pct, config)


# ── Private per-setup computations ───────────────────────────────────────────


def _pullback_entry_levels(
    price: float,
    indicator: AssetIndicators,
    atr_pct: float | None,
    config: EntryConfig,
) -> EntryLevels:
    """Pullback: anchor to the nearest qualified support below price."""
    snap = indicator.tf_4h
    candidates: list[tuple[float | None, str]] = [
        (snap.ema_20, ANCHOR_EMA20),
        (snap.ema_50, ANCHOR_EMA50),
        (snap.vwap, ANCHOR_VWAP),
    ]
    qualified = [
        (v, name)
        for v, name in candidates
        if v is not None and v <= price * (1.0 - config.min_pullback_discount)
    ]

    if qualified:
        anchor_val, anchor_type = max(qualified, key=lambda x: x[0])
        preferred = round(anchor_val * (1.0 + _PULLBACK_FILL_BUFFER), 8)
        anchor_stored: float | None = anchor_val
    else:
        pullback_pct = max((atr_pct or 5.0) / 100.0 * _PULLBACK_ATR_MULT, _PULLBACK_ATR_MIN)
        anchor_type = ANCHOR_ATR
        preferred = round(price * (1.0 - pullback_pct), 8)
        anchor_stored = None

    max_entry = round(preferred * (1.0 + config.max_chase_pullback), 8)
    return EntryLevels(
        preferred_entry=preferred,
        max_entry=max_entry,
        support_anchor_type=anchor_type,
        support_anchor_value=anchor_stored,
    )


def _breakout_entry_levels(
    symbol: str,
    price: float,
    metrics: MarketMetrics,
    config: EntryConfig,
) -> EntryLevels:
    """Breakout-trigger: anchor to the reconstructed 20-day high."""
    dist = metrics.dist_from_20d_high
    if dist is None:
        raise EntryEngineError(
            ENTRY_REJECT_MISSING_DIST_20D,
            f"{symbol}: breakout_trigger setup requires dist_from_20d_high",
        )

    # Reconstruct: dist = (price − high) / high  →  high = price / (1 + dist)
    twenty_d_high = round(price / (1.0 + dist), 8)

    if dist >= -0.015:
        # Price is at or above the 20d high — enter just below current market
        anchor_type = ANCHOR_ABOVE_20D_HIGH
        preferred = round(price * (1.0 - _BREAKOUT_AT_HIGH_BUFFER), 8)
    else:
        # Price approaching the high — trigger just above the breakout level
        anchor_type = ANCHOR_20D_HIGH_TRIGGER
        preferred = round(twenty_d_high * (1.0 + _BREAKOUT_TRIGGER_BUFFER), 8)

    max_entry = round(twenty_d_high * (1.0 + config.max_chase_breakout), 8)
    return EntryLevels(
        preferred_entry=preferred,
        max_entry=max_entry,
        support_anchor_type=anchor_type,
        support_anchor_value=twenty_d_high,
    )


def _reclaim_entry_levels(
    symbol: str,
    price: float,
    indicator: AssetIndicators,
    config: EntryConfig,
) -> EntryLevels:
    """Reclaim: anchor to the key level that price has just re-crossed from below.

    The anchor must be strictly below current price (at least 0.1 %) and
    within 4 % below price — the "freshly reclaimed" zone.
    """
    snap = indicator.tf_4h
    candidates: list[tuple[float | None, str]] = [
        (snap.ema_20, ANCHOR_EMA20),
        (snap.vwap, ANCHOR_VWAP),
    ]
    near = [
        (v, name)
        for v, name in candidates
        if v is not None
        and price * (1.0 - _RECLAIM_MAX_PROXIMITY) <= v <= price * (1.0 - _RECLAIM_MIN_PROXIMITY)
    ]

    if not near:
        raise EntryEngineError(
            ENTRY_REJECT_NO_QUALIFIED_ANCHOR,
            f"{symbol}: reclaim setup found no level within "
            f"[{_RECLAIM_MIN_PROXIMITY * 100:.1f}%, {_RECLAIM_MAX_PROXIMITY * 100:.0f}%] "
            f"below price {price}",
        )

    anchor_val, anchor_type = max(near, key=lambda x: x[0])
    preferred = round(anchor_val * (1.0 + _RECLAIM_FILL_BUFFER), 8)
    max_entry = round(anchor_val * (1.0 + config.max_chase_reclaim), 8)
    return EntryLevels(
        preferred_entry=preferred,
        max_entry=max_entry,
        support_anchor_type=anchor_type,
        support_anchor_value=anchor_val,
    )
