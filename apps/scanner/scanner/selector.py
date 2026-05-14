"""Candidate Selector + Trade Parameters — PR 9 / PR entry-engine.

Selects the top-N clean and ugly scored candidates, then computes
deterministic entry/exit/stop/size parameters for each.

Public API:
    run_candidate_selector(
        scoring_result: ScoringResult,
        filter_result:  FilterResult,
        config:         SelectorConfig | None = None,
    ) -> SelectionResult

Internal API (exposed for unit testing):
    compute_trade_parameters(metrics, indicator, score, category, config) -> TradeParameters
    _assign_size_bucket(score, metrics, category)                         -> str
    _compute_stop_pct(category, atr_pct, config)                         -> float

Entry engine (see entry_engine.py)
    setup_type = classify_setup(metrics, indicator)
    levels     = compute_entry_levels(setup_type, metrics, indicator, config)
    preferred_entry  = levels.preferred_entry   — ideal limit order price
    max_entry        = levels.max_entry         — chase ceiling
    entry_price_low  = preferred × (1 − 0.5 %)  — limit-order floor
    Validity gates:
      pullback/reclaim: max_entry must be < current price
      breakout_trigger: preferred_entry must be ≤ current × (1 + max_chase_current_price_pct)

Stop loss
    stop_pct is ATR-based, clamped to category constraints from migration 0012:
        clean: stop_pct = ATR × 1.5, constrained to [3 %, 12 %]
        ugly:  stop_pct = ATR × 2.0, constrained to [8 %, 15 %]
    stop_loss = entry × (1 − stop_pct)      — always satisfies stop < entry.

Exit price
    Minimum R:R enforced first (clean.min_reward_risk=2.0, ugly=2.5):
        rr_exit = entry + min_rr × (entry − stop)
    Technical target used when 20d-high data is available and meaningful
    (price ≥ 3 % below 20d high):
        20d_high ≈ price / (1 + dist_from_20d_high)   [dist is negative]
        tech_exit = 20d_high × 0.97   (3 % below high — conservative)
        exit = max(rr_exit, tech_exit)
    Hard floor: exit ≥ entry × 1.05 (minimum 5 % target).

Size bucket assignment (from migration 0012 sizing thresholds)
    clean:
        score ≥ 82 AND vol_7d ≥ $50 M → '20k+'
        score ≥ 75 AND vol_7d ≥ $20 M → '10k-20k'
        score ≥ 70 AND vol_7d ≥ $10 M → '5k-10k'
        else                           → '2k-5k'
    ugly:
        score ≥ 70 AND vol_7d ≥ $5 M  → '5k-10k'
        score ≥ 65                     → '2k-5k'
        else                           → '2k'

Notes string (human-readable rationale for Discord / dashboard)
    "trend:<> | ema:<> | vwap:<> | rsi:<> | vol:<>x | ret7d:<>%"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scanner.entry_engine import (
    EntryEngineError,
    classify_setup,
    compute_entry_levels,
)
from scanner.models import (
    AssetIndicators,
    EntryRejection,
    FilterResult,
    MarketMetrics,
    ScoreBreakdown,
    ScoredCandidate,
    ScoringResult,
    SelectionResult,
    TradeParameters,
)
from scanner.rejection_reasons import (
    ENTRY_REJECT_BREAKOUT_CHASE_CEILING,
    ENTRY_REJECT_PULLBACK_MAX_ABOVE_PRICE,
    ENTRY_REJECT_RECLAIM_MAX_ABOVE_PRICE,
)

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SelectorConfig:
    """Candidate selection and trade parameter thresholds.

    Defaults match migration 0012 strategy_settings seed values.
    """

    max_clean_candidates: int = 10
    """scanner.max_clean_candidates — top-N clean candidates to select."""

    max_ugly_candidates: int = 10
    """scanner.max_ugly_candidates — top-N ugly candidates to select."""

    clean_stop_atr_multiplier: float = 1.5
    """ATR multiplier for clean stop placement (stop = entry × (1 − ATR × mult))."""

    clean_min_stop_pct: float = 0.03
    """Minimum stop distance for clean candidates (3 %)."""

    clean_max_stop_pct: float = 0.12
    """Maximum stop distance for clean candidates (12 %)."""

    clean_min_reward_risk: float = 2.0
    """clean.min_reward_risk — minimum R:R ratio for clean trade parameters."""

    ugly_stop_atr_multiplier: float = 2.0
    """ATR multiplier for ugly stop (wider than clean; needs more room)."""

    ugly_min_stop_pct: float = 0.08
    """ugly.min_stop_pct — minimum stop distance for ugly candidates (8 %)."""

    ugly_max_stop_pct: float = 0.15
    """ugly.max_stop_pct — maximum stop distance for ugly candidates (15 %)."""

    ugly_min_reward_risk: float = 2.5
    """ugly.min_reward_risk — minimum R:R ratio for ugly trade parameters."""

    min_pullback_discount: float = 0.02
    """Min fractional discount a support level must offer to qualify (2 %)."""

    max_pullback_depth: float = 0.20
    """Max fractional distance below market before fill is deemed unreachable (20 %)."""

    max_chase_pullback: float = 0.01
    """max_entry margin above preferred_entry for pullback setups (1 %)."""

    max_chase_breakout: float = 0.015
    """max_entry margin above 20d high for breakout setups (1.5 %)."""

    max_chase_reclaim: float = 0.02
    """max_entry margin above reclaim anchor (2 %)."""

    max_chase_current_price_pct: float = 0.03
    """Breakout only: max preferred_entry above current price (3 %)."""


# ── Internal helpers ─────────────────────────────────────────────────────────


def _compute_stop_pct(
    category: str,
    atr_pct: float | None,
    config: SelectorConfig,
) -> float:
    """Compute stop distance as a fraction of entry price.

    Uses ATR-based sizing clamped to category-specific [min, max] bounds.
    Falls back to the midpoint of the allowed range when ATR is unavailable.
    """
    if category == "clean":
        base = (atr_pct / 100.0 * config.clean_stop_atr_multiplier) if atr_pct else 0.06
        return max(config.clean_min_stop_pct, min(base, config.clean_max_stop_pct))
    base = (atr_pct / 100.0 * config.ugly_stop_atr_multiplier) if atr_pct else 0.10
    return max(config.ugly_min_stop_pct, min(base, config.ugly_max_stop_pct))


def _assign_size_bucket(
    score: ScoreBreakdown,
    metrics: MarketMetrics,
    category: str,
) -> str:
    """Assign a size bucket from migration 0012 sizing thresholds.

    Returns a string matching the crecs_size_bucket_check DB constraint:
        '2k' | '2k-5k' | '5k-10k' | '10k-20k' | '20k+'
    """
    s = score.score_total
    v7 = metrics.volume_7d_avg_usd or 0.0

    if category == "clean":
        if s >= 82 and v7 >= 50_000_000:
            return "20k+"
        if s >= 75 and v7 >= 20_000_000:
            return "10k-20k"
        if s >= 70 and v7 >= 10_000_000:
            return "5k-10k"
        return "2k-5k"

    # ugly
    if s >= 70 and v7 >= 5_000_000:
        return "5k-10k"
    if s >= 65:
        return "2k-5k"
    return "2k"


def _build_notes(metrics: MarketMetrics, indicator: AssetIndicators) -> str:
    """Build a compact human-readable rationale string for Discord / dashboard."""
    snap = indicator.tf_4h
    parts = [
        f"trend:{snap.trend_state or 'n/a'}",
        f"ema:{snap.ema_alignment or 'n/a'}",
        f"vwap:{snap.vwap_state or 'n/a'}",
        f"rsi:{snap.rsi_14:.0f}" if snap.rsi_14 is not None else "rsi:n/a",
        (
            f"vol:{metrics.volume_ratio_20d:.1f}x"
            if metrics.volume_ratio_20d is not None
            else "vol:n/a"
        ),
        (f"ret7d:{metrics.return_7d:+.1%}" if metrics.return_7d is not None else "ret7d:n/a"),
    ]
    return " | ".join(parts)


# ── Public trade parameter computation ───────────────────────────────────────


def compute_trade_parameters(
    metrics: MarketMetrics,
    indicator: AssetIndicators,
    score: ScoreBreakdown,
    category: str,
    config: SelectorConfig,
) -> TradeParameters:
    """Compute entry/exit/stop/size trade parameters for one candidate.

    All DB constraints are satisfied by construction:
        stop_loss < entry_price
        exit_price > entry_price
        entry_price_low <= entry_price_high

    Args:
        metrics:   MarketMetrics (PR 7) — price, ATR, dist from highs.
        indicator: AssetIndicators (PR 6) — trend state, RSI, EMA levels.
        score:     ScoreBreakdown (PR 8) — total score for size bucket assignment.
        category:  'clean' | 'ugly' — determines stop / R:R constraints.
        config:    SelectorConfig thresholds.

    Returns:
        TradeParameters with all DB-safe values populated.
    """
    price = metrics.price_usd
    atr_pct = metrics.atr_pct_7d

    # ── Entry zone: setup-aware, from entry_engine ────────────────────────────
    setup_type = classify_setup(metrics, indicator)
    levels = compute_entry_levels(setup_type, metrics, indicator, config)

    entry_price = levels.preferred_entry  # alias kept for backward compat
    entry_price_low = round(levels.preferred_entry * 0.995, 8)
    entry_price_high = levels.max_entry  # max_entry replaces old ±0.5 % high

    # Validity gate — setup-aware.
    # pullback / reclaim: max_entry must sit entirely below market.
    # breakout_trigger:   preferred may be above market, but capped at +max_chase_current_price_pct.
    if setup_type != "breakout_trigger" and entry_price_high >= price:
        reason = (
            ENTRY_REJECT_PULLBACK_MAX_ABOVE_PRICE
            if setup_type == "pullback"
            else ENTRY_REJECT_RECLAIM_MAX_ABOVE_PRICE
        )
        raise EntryEngineError(
            reason,
            f"{metrics.symbol}: {setup_type} max_entry {entry_price_high} "
            f">= current price {price}; rejecting",
        )
    if setup_type == "breakout_trigger" and entry_price > price * (
        1.0 + config.max_chase_current_price_pct
    ):
        raise EntryEngineError(
            ENTRY_REJECT_BREAKOUT_CHASE_CEILING,
            f"{metrics.symbol}: breakout preferred_entry {entry_price} "
            f"> current price × {1 + config.max_chase_current_price_pct:.3f}; "
            "rejecting over-chased breakout",
        )

    # ── Stop loss ──────────────────────────────────────────────────────────────
    stop_pct = _compute_stop_pct(category, atr_pct, config)
    stop_loss = round(entry_price * (1.0 - stop_pct), 8)
    # stop_loss < entry_price is guaranteed: stop_pct > 0.

    # ── Exit price ─────────────────────────────────────────────────────────────
    min_rr = config.clean_min_reward_risk if category == "clean" else config.ugly_min_reward_risk
    risk = entry_price - stop_loss
    rr_exit = entry_price + min_rr * risk

    # Technical target: derived from 20d rolling high when available.
    dist_20d = metrics.dist_from_20d_high
    if dist_20d is not None and dist_20d < -0.03:
        # dist_from_20d_high = (close − 20d_high) / 20d_high  →  20d_high = close / (1 + dist)
        # dist is negative so (1 + dist) < 1  →  20d_high > close ✓
        twenty_d_high = price / (1.0 + dist_20d)
        tech_exit = twenty_d_high * 0.97  # 3 % below 20d high — conservative target
        exit_price = round(max(rr_exit, tech_exit), 8)
    else:
        exit_price = round(rr_exit, 8)

    # Hard floor: at minimum a 5 % gain over entry.
    exit_price = max(exit_price, round(entry_price * 1.05, 8))
    # exit_price > entry_price is guaranteed by the 5 % floor.

    # ── Derived metrics ────────────────────────────────────────────────────────
    expected_gain_pct = round((exit_price - entry_price) / entry_price * 100, 4)
    reward_risk_ratio = round((exit_price - entry_price) / (entry_price - stop_loss), 3)

    # ── Size bucket & notes ────────────────────────────────────────────────────
    size_bucket = _assign_size_bucket(score, metrics, category)
    notes = _build_notes(metrics, indicator)

    distance_to_entry_pct = round((entry_price - price) / price * 100, 2)

    return TradeParameters(
        symbol=metrics.symbol,
        entry_price=entry_price,
        entry_price_low=entry_price_low,
        entry_price_high=entry_price_high,
        exit_price=exit_price,
        stop_loss=stop_loss,
        suggested_size_bucket=size_bucket,
        expected_gain_pct=expected_gain_pct,
        reward_risk_ratio=reward_risk_ratio,
        notes=notes,
        current_price=price,
        distance_to_entry_pct=distance_to_entry_pct,
        setup_type=setup_type,
        preferred_entry=levels.preferred_entry,
        max_entry=levels.max_entry,
        support_anchor_type=levels.support_anchor_type,
        support_anchor_value=levels.support_anchor_value,
    )


# ── Pipeline entry point ──────────────────────────────────────────────────────


def run_candidate_selector(
    scoring_result: ScoringResult,
    filter_result: FilterResult,
    config: SelectorConfig | None = None,
) -> SelectionResult:
    """Select top-N clean and ugly candidates and compute their trade parameters.

    Picks the top `max_clean_candidates` from ScoringResult.clean (already
    sorted by score_total desc by run_scoring_engine) and similarly for ugly.

    Args:
        scoring_result: ScoringResult from run_scoring_engine() (PR 8).
        filter_result:  FilterResult from run_hard_filter() (PR 7), used to
                        look up MarketMetrics and AssetIndicators by symbol.
        config:         Selection thresholds. Defaults to SelectorConfig().

    Returns:
        SelectionResult with clean and ugly ScoredCandidate lists.
    """
    if config is None:
        config = SelectorConfig()

    if scoring_result.clean_count == 0 and scoring_result.ugly_count == 0:
        log.warning("run_candidate_selector called with no clean or ugly candidates")
        return SelectionResult()

    metrics_by_symbol: dict[str, MarketMetrics] = {
        m.symbol: m for m in filter_result.passed_metrics
    }
    indicators_by_symbol: dict[str, AssetIndicators] = {
        i.symbol: i for i in filter_result.passed_indicators
    }

    def _build(
        scores: list[ScoreBreakdown],
        category: str,
        max_n: int,
    ) -> tuple[list[ScoredCandidate], list[EntryRejection]]:
        candidates: list[ScoredCandidate] = []
        rejections: list[EntryRejection] = []
        for rank, score_bd in enumerate(scores[:max_n], start=1):
            sym = score_bd.symbol
            metrics = metrics_by_symbol.get(sym)
            indicator = indicators_by_symbol.get(sym)
            if metrics is None or indicator is None:
                log.warning("%s missing from filter_result; skipping", sym)
                continue
            try:
                trade = compute_trade_parameters(metrics, indicator, score_bd, category, config)
                candidates.append(
                    ScoredCandidate(
                        symbol=sym,
                        kraken_pair=metrics.kraken_pair,
                        category=category,
                        rank=rank,
                        score=score_bd,
                        trade=trade,
                        market=metrics,
                        indicators=indicator,
                    )
                )
            except EntryEngineError as exc:
                setup_type = classify_setup(metrics, indicator)
                log.info(
                    "%s entry rejected (%s): %s",
                    sym,
                    exc.reason,
                    exc,
                )
                rejections.append(
                    EntryRejection(
                        symbol=sym,
                        category=category,
                        rank=rank,
                        setup_type=setup_type,
                        rejection_reason=exc.reason,
                        metadata={
                            "score_total": score_bd.score_total,
                            "probability_pct": score_bd.probability_pct,
                            "current_price": metrics.price_usd,
                        },
                    )
                )
            except Exception as exc:
                log.warning("%s trade parameter computation failed: %s", sym, exc)
        return candidates, rejections

    log.info(
        "Stage 6 — selecting from %d clean / %d ugly scored assets",
        scoring_result.clean_count,
        scoring_result.ugly_count,
    )
    clean, clean_rejected = _build(scoring_result.clean, "clean", config.max_clean_candidates)
    ugly, ugly_rejected = _build(scoring_result.ugly, "ugly", config.max_ugly_candidates)
    result = SelectionResult(clean=clean, ugly=ugly, rejected=clean_rejected + ugly_rejected)

    log.info(
        "Stage 6 complete — %d clean + %d ugly candidates selected",
        len(clean),
        len(ugly),
    )
    if clean:
        c = clean[0]
        log.info(
            "Top clean: %s  score=%.1f  rr=%.2f  size=%s",
            c.symbol,
            c.score.score_total,
            c.trade.reward_risk_ratio,
            c.trade.suggested_size_bucket,
        )
    if ugly:
        u = ugly[0]
        log.info(
            "Top ugly:  %s  score=%.1f  rr=%.2f  size=%s",
            u.symbol,
            u.score.score_total,
            u.trade.reward_risk_ratio,
            u.trade.suggested_size_bucket,
        )
    return result
