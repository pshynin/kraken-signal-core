"""Scoring Engine — PR 8.

Assigns a deterministic 9-factor score (0–100) to every asset that cleared
the hard filter, then classifies each asset into a category.

Public API:
    run_scoring_engine(
        filter_result: FilterResult,
        config:        ScoringConfig | None = None,
    ) -> ScoringResult

Internal API (exposed for unit testing):
    score_asset(metrics, indicator, config)  -> ScoreBreakdown
    _score_liquidity(metrics)                -> float /20
    _score_upside(metrics, indicator)        -> float /15
    _score_volatility(metrics)               -> float /10
    _score_structure(indicator)              -> float /15
    _score_rel_strength(metrics)             -> float /10
    _score_volume(metrics, indicator)        -> float /10
    _score_catalyst(metrics, indicator)      -> float /10
    _score_supply_risk(metrics)              -> float /5
    _score_execution(metrics, indicator)     -> float /5
    _probability_pct(score_total)            -> float | None
    _assign_category(score, metrics, ...)    -> str

Score factor designs:
    score_liquidity  — volume_24h, volume_7d_avg, spread proxy
    score_upside     — dist_from_7d_high (5-20% below = sweet spot), RSI zone, return_7d
    score_volatility — ATR % in optimal band (6-12% = max 10)
    score_structure  — 4h trend + EMA alignment + VWAP state + 1h confluence
    score_rel_strength — return_vs_btc_7d; falls back to return_7d if no BTC
    score_volume     — volume_ratio_20d (20-day expansion) + 4h current candle vs MA20
    score_catalyst   — return_3d momentum, VWAP reclaim setup, near 7d high
    score_supply_risk — dist_from_20d_high (overhead supply proxy)
    score_execution  — price vs EMA20 proximity + spread quality

Category assignment (defaults from migration 0012 strategy_settings seed):
    clean     — score >= 70 + vol_24h >= $2M + vol_7d >= $5M + RSI [52,68]
                + return_3d <= 30% + price_vs_ema20 <= 12%
    ugly      — score >= 62 + RSI [50,72]
    watchlist — score >= 55
    (anything below 55 stays scored but unclassified; the DB persister PR 10
     will record these with category=NULL)

Probability map (heuristic percentile, from migration 0012):
    >= 85 → 90%
    >= 78 → 84%
    >= 70 → 77%
    >= 62 → 69%
    <  62 → None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scanner.models import (
    AssetIndicators,
    FilterResult,
    MarketMetrics,
    ScoreBreakdown,
    ScoringResult,
)

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Probability map: (score_floor, probability_pct) sorted descending.
# Matches migration 0012 scoring.probability_map seed value.
_PROB_MAP: tuple[tuple[float, float], ...] = (
    (85.0, 90.0),
    (78.0, 84.0),
    (70.0, 77.0),
    (62.0, 69.0),
)

# Maximum points per factor; must sum to 100.
_MAX_LIQUIDITY = 20
_MAX_UPSIDE = 15
_MAX_VOLATILITY = 10
_MAX_STRUCTURE = 15
_MAX_REL_STRENGTH = 10
_MAX_VOLUME = 10
_MAX_CATALYST = 10
_MAX_SUPPLY_RISK = 5
_MAX_EXECUTION = 5


# ── Scoring configuration ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoringConfig:
    """Category qualification thresholds. Defaults match migration 0012 seed values."""

    clean_min_score: float = 70.0
    """Minimum score_total for clean category (clean.min_score)."""

    clean_min_volume_24h_usd: float = 2_000_000.0
    """clean.min_volume_24h_usd — 24h dollar volume floor for clean."""

    clean_min_volume_7d_avg_usd: float = 5_000_000.0
    """clean.min_volume_7d_avg_usd — 7d avg dollar volume floor for clean."""

    clean_rsi_preferred_min: float = 52.0
    """clean.rsi_preferred_min — lower RSI bound for clean category."""

    clean_rsi_preferred_max: float = 68.0
    """clean.rsi_preferred_max — upper RSI bound for clean category."""

    clean_max_return_3d: float = 0.30
    """clean.max_return_3d — anti-chase 3d return ceiling for clean."""

    clean_max_price_vs_ema20_pct: float = 12.0
    """clean.max_price_vs_ema20_pct — anti-chase EMA20 distance ceiling for clean."""

    ugly_min_score: float = 62.0
    """ugly.min_score — minimum score_total for ugly category."""

    ugly_rsi_preferred_min: float = 50.0
    """ugly.rsi_preferred_min — lower RSI bound for ugly category."""

    ugly_rsi_preferred_max: float = 72.0
    """ugly.rsi_preferred_max — upper RSI bound for ugly category."""

    watchlist_min_score: float = 55.0
    """Minimum score_total to appear on the watchlist."""

    prob_map: tuple[tuple[float, float], ...] = _PROB_MAP
    """Score-floor → probability-pct tiers. Defaults to migration 0012 values.
    Overridden by settings.py when strategy_settings is loaded from Supabase.
    """


# ── Probability mapping ───────────────────────────────────────────────────────


def _prob_from_map(
    score_total: float,
    prob_map: tuple[tuple[float, float], ...],
) -> float | None:
    """Map score_total to a heuristic probability percentile using the given map.

    Used by score_asset() so the map can be overridden via ScoringConfig.
    """
    for floor, pct in prob_map:
        if score_total >= floor:
            return pct
    return None


def _probability_pct(score_total: float) -> float | None:
    """Map score_total to a heuristic success probability percentile.

    Uses the module-level _PROB_MAP tiers from migration 0012.
    Returns None when score_total is below the lowest tier (62).
    Delegates to _prob_from_map for the actual lookup.
    """
    return _prob_from_map(score_total, _PROB_MAP)


# ── Sub-scorers ───────────────────────────────────────────────────────────────


def _score_liquidity(metrics: MarketMetrics) -> float:
    """Liquidity and tradability — /20.

    Components:
        8 pts — 24h dollar volume tier
        8 pts — 7-day average dollar volume tier
        4 pts — spread proxy (lower = better)
    """
    score = 0.0

    v24 = metrics.volume_24h_usd or 0.0
    if v24 >= 20_000_000:
        score += 8.0
    elif v24 >= 10_000_000:
        score += 7.0
    elif v24 >= 5_000_000:
        score += 6.0
    elif v24 >= 2_000_000:
        score += 5.0
    elif v24 >= 1_000_000:
        score += 4.0
    elif v24 >= 300_000:
        score += 2.0

    v7 = metrics.volume_7d_avg_usd or 0.0
    if v7 >= 15_000_000:
        score += 8.0
    elif v7 >= 5_000_000:
        score += 7.0
    elif v7 >= 2_000_000:
        score += 6.0
    elif v7 >= 1_000_000:
        score += 4.0
    elif v7 >= 750_000:
        score += 2.0

    sp = metrics.spread_pct
    if sp is None:
        score += 2.0
    elif sp <= 0.005:
        score += 4.0
    elif sp <= 0.010:
        score += 3.0
    elif sp <= 0.020:
        score += 2.0
    elif sp <= 0.040:
        score += 1.0

    return min(score, float(_MAX_LIQUIDITY))


def _score_upside(metrics: MarketMetrics, indicator: AssetIndicators) -> float:
    """7-10 day upside feasibility — /15.

    Components:
        6 pts — distance from 7-day high (5-20% below = optimal)
        5 pts — RSI position in preferred zone (55-65 = optimal momentum)
        4 pts — 7-day return (5-25% = optimal, positive trend)
    """
    score = 0.0

    dist = metrics.dist_from_7d_high
    if dist is None:
        score += 3.0
    elif -0.20 <= dist <= -0.05:
        score += 6.0  # ideal: 5-20% below 7d high, room to move
    elif -0.30 <= dist < -0.20:
        score += 4.0  # further below — weakening trend
    elif dist > -0.05:
        score += 3.0  # near or at high — less room
    else:
        score += 2.0  # > 30% below, potential damage

    rsi = indicator.tf_4h.rsi_14
    if rsi is None:
        score += 3.0
    elif 55.0 <= rsi <= 65.0:
        score += 5.0  # optimal momentum zone
    elif 52.0 <= rsi < 55.0 or 65.0 < rsi <= 68.0:
        score += 4.0
    elif 48.0 <= rsi < 52.0 or 68.0 < rsi <= 72.0:
        score += 3.0
    else:
        score += 1.0  # outside preferred ranges

    ret7 = metrics.return_7d
    if ret7 is None:
        score += 2.0
    elif 0.05 <= ret7 <= 0.25:
        score += 4.0  # 5-25% — ideal momentum
    elif 0.02 <= ret7 < 0.05:
        score += 3.0
    elif ret7 > 0.25:
        score += 2.0  # extended but moving
    elif ret7 >= 0:
        score += 2.0  # flat
    else:
        score += 1.0  # negative

    return min(score, float(_MAX_UPSIDE))


def _score_volatility(metrics: MarketMetrics) -> float:
    """ATR volatility sweet spot — /10.

    6-12% ATR on 4h is optimal (enough movement for meaningful 7-10d trade,
    but not so wild that execution degrades). Below 4% too quiet; above 25%
    execution risk rises sharply.
    """
    atr = metrics.atr_pct_7d
    if atr is None:
        return 5.0
    if 6.0 <= atr <= 12.0:
        return 10.0
    if 12.0 < atr <= 18.0:
        return 8.0  # acceptable for both categories
    if 4.0 <= atr < 6.0:
        return 7.0  # valid for clean, below ugly min
    if 18.0 < atr <= 25.0:
        return 5.0  # ugly territory
    if 25.0 < atr <= 30.0:
        return 2.0  # near ceiling; execution risky
    return 1.0  # < 4% (should be filtered) or > 30%


def _score_structure(indicator: AssetIndicators) -> float:
    """Multi-timeframe EMA structure quality — /15.

    Components:
        6 pts — 4h trend_state
        5 pts — 4h EMA alignment
        2 pts — 4h VWAP state
        2 pts — 1h timeframe confluence with 4h (bonus)
    """
    snap4h = indicator.tf_4h
    snap1h = indicator.tf_1h
    score = 0.0

    trend_pts: dict[str, float] = {
        "strong_up": 6.0,
        "up": 5.0,
        "neutral": 2.0,
        "down": 1.0,
        "strong_down": 0.0,
    }
    score += trend_pts.get(snap4h.trend_state or "", 2.0)

    align_pts: dict[str, float] = {
        "bullish": 5.0,
        "partial_bullish": 4.0,
        "neutral": 2.0,
        "bearish": 0.0,
    }
    score += align_pts.get(snap4h.ema_alignment or "", 2.0)

    vwap_pts: dict[str, float] = {"above": 2.0, "reclaiming": 1.0, "below": 0.0}
    score += vwap_pts.get(snap4h.vwap_state or "", 0.0)

    bullish_4h = snap4h.trend_state in ("strong_up", "up")
    if bullish_4h and snap1h.trend_state in ("strong_up", "up"):
        score += 2.0  # multi-TF alignment bonus
    elif bullish_4h and snap1h.trend_state == "neutral":
        score += 1.0

    return min(score, float(_MAX_STRUCTURE))


def _score_rel_strength(metrics: MarketMetrics) -> float:
    """Relative strength vs BTC over 7 days — /10.

    Uses return_vs_btc_7d when available; falls back to absolute return_7d
    if BTC was not in the scanned universe.
    """
    rs = metrics.return_vs_btc_7d

    if rs is None:
        ret7 = metrics.return_7d
        if ret7 is None:
            return 5.0
        if ret7 >= 0.10:
            return 7.0
        if ret7 >= 0.05:
            return 6.0
        if ret7 >= 0.0:
            return 5.0
        return 3.0

    if rs >= 0.10:
        return 10.0
    if rs >= 0.05:
        return 8.0
    if rs >= 0.02:
        return 6.0
    if rs >= 0.0:
        return 4.0
    if rs >= -0.05:
        return 2.0
    return 0.0


def _score_volume(metrics: MarketMetrics, indicator: AssetIndicators) -> float:
    """Volume expansion / confirmation — /10.

    Components:
        6 pts — volume_ratio_20d (current 24h vs 20-day average)
        4 pts — last 4h candle volume vs volume MA20
    """
    score = 0.0

    ratio = metrics.volume_ratio_20d
    if ratio is None:
        score += 3.0
    elif ratio >= 2.0:
        score += 6.0
    elif ratio >= 1.5:
        score += 5.0
    elif ratio >= 1.2:
        score += 4.0
    elif ratio >= 1.0:
        score += 3.0
    elif ratio >= 0.7:
        score += 2.0
    else:
        score += 0.0

    cur_vol = indicator.tf_4h.volume_current
    ma_vol = indicator.tf_4h.volume_ma_20
    if cur_vol is None or ma_vol is None or ma_vol == 0:
        score += 2.0
    else:
        candle_ratio = cur_vol / ma_vol
        if candle_ratio >= 1.5:
            score += 4.0
        elif candle_ratio >= 1.2:
            score += 3.0
        elif candle_ratio >= 0.8:
            score += 2.0
        else:
            score += 1.0

    return min(score, float(_MAX_VOLUME))


def _score_catalyst(metrics: MarketMetrics, indicator: AssetIndicators) -> float:
    """Catalyst / market attention proxy — /10.

    Components:
        5 pts — 3-day return (fresh momentum, anti-chase considered)
        3 pts — VWAP + trend state momentum setup
        2 pts — approaching 7-day high (potential breakout catalyst)
    """
    score = 0.0

    ret3 = metrics.return_3d
    if ret3 is None:
        score += 3.0
    elif 0.03 <= ret3 <= 0.15:
        score += 5.0  # fresh catalyst in clean range
    elif 0.01 <= ret3 < 0.03:
        score += 4.0  # mild positive
    elif ret3 > 0.15:
        score += 2.0  # extended; anti-chase caution
    elif ret3 >= -0.05:
        score += 2.0  # flat / slight pullback
    else:
        score += 1.0  # notable decline

    snap = indicator.tf_4h
    bullish = snap.trend_state in ("strong_up", "up")
    if snap.vwap_state == "reclaiming" and bullish:
        score += 3.0  # VWAP reclaim + bullish trend = classic momentum setup
    elif snap.vwap_state == "above" and bullish:
        score += 2.0
    elif bullish:
        score += 1.0

    dist = metrics.dist_from_7d_high
    if dist is not None and -0.10 <= dist <= -0.02:
        score += 2.0  # approaching 7d high = potential breakout
    elif dist is not None and dist > -0.02:
        score += 1.0  # at / just above 7d high

    return min(score, float(_MAX_CATALYST))


def _score_supply_risk(metrics: MarketMetrics) -> float:
    """Overhead supply risk from 20-day high distance — /5.

    Less distance below the 20d high = more overhead supply resistance = lower score.
    Neutral (3/5) when dist_from_20d_high is unavailable.
    """
    dist = metrics.dist_from_20d_high
    if dist is None:
        return 3.0
    if dist <= -0.25:
        return 5.0  # 25%+ below 20d high — minimal overhead supply
    if dist <= -0.15:
        return 4.0
    if dist <= -0.08:
        return 3.0
    if dist <= -0.03:
        return 2.0
    return 1.0  # at or near 20d high — heavy supply


def _score_execution(metrics: MarketMetrics, indicator: AssetIndicators) -> float:
    """Entry/exit execution clarity — /5.

    Components:
        3 pts — price vs EMA20 proximity (0-5% above EMA20 = ideal entry zone)
        2 pts — spread quality
    """
    score = 0.0

    pve20 = indicator.tf_4h.price_vs_ema20_pct
    if pve20 is None:
        score += 2.0
    elif 0.0 <= pve20 <= 5.0:
        score += 3.0  # price just above EMA20 = clean pullback entry
    elif -5.0 <= pve20 < 0.0 or 5.0 < pve20 <= 12.0:
        score += 2.0  # slight dip or moderate extension
    else:
        score += 1.0  # overextended or well below EMA20

    sp = metrics.spread_pct
    if sp is None:
        score += 1.0
    elif sp <= 0.010:
        score += 2.0
    elif sp <= 0.025:
        score += 1.0

    return min(score, float(_MAX_EXECUTION))


# ── Category assignment ───────────────────────────────────────────────────────


def _assign_category(
    score_total: float,
    metrics: MarketMetrics,
    indicator: AssetIndicators,
    config: ScoringConfig,
) -> str:
    """Classify asset into clean | ugly | watchlist based on score and thresholds.

    Clean requires: score >= 70 AND volume floors AND RSI in preferred range
                   AND anti-chase return/EMA20 constraints.
    Ugly requires:  score >= 62 AND RSI in ugly preferred range.
    Watchlist:      score >= 55 (doesn't qualify for either tradeable category).
    Returns 'watchlist' for all others that passed the hard filter but scored < 55.
    """
    rsi = indicator.tf_4h.rsi_14
    ret3 = metrics.return_3d
    pve20 = indicator.tf_4h.price_vs_ema20_pct

    if score_total >= config.clean_min_score:
        vol_ok = (metrics.volume_24h_usd or 0.0) >= config.clean_min_volume_24h_usd and (
            metrics.volume_7d_avg_usd or 0.0
        ) >= config.clean_min_volume_7d_avg_usd
        rsi_ok = rsi is None or (
            config.clean_rsi_preferred_min <= rsi <= config.clean_rsi_preferred_max
        )
        ret_ok = ret3 is None or ret3 <= config.clean_max_return_3d
        ema_ok = pve20 is None or pve20 <= config.clean_max_price_vs_ema20_pct

        if vol_ok and rsi_ok and ret_ok and ema_ok:
            return "clean"

    if score_total >= config.ugly_min_score:
        rsi_ok = rsi is None or (
            config.ugly_rsi_preferred_min <= rsi <= config.ugly_rsi_preferred_max
        )
        if rsi_ok:
            return "ugly"

    if score_total >= config.watchlist_min_score:
        return "watchlist"

    return "watchlist"


# ── Public API ────────────────────────────────────────────────────────────────


def score_asset(
    metrics: MarketMetrics,
    indicator: AssetIndicators,
    config: ScoringConfig,
) -> ScoreBreakdown:
    """Compute all 9 scoring factors and classify one asset.

    Args:
        metrics:   MarketMetrics from compute_market_metrics() (PR 7).
        indicator: AssetIndicators from run_indicator_engine() (PR 6).
        config:    Category thresholds. Defaults to ScoringConfig().

    Returns:
        ScoreBreakdown with score_total and category classification.
    """
    liq = _score_liquidity(metrics)
    ups = _score_upside(metrics, indicator)
    vol = _score_volatility(metrics)
    struct = _score_structure(indicator)
    rs = _score_rel_strength(metrics)
    volume = _score_volume(metrics, indicator)
    cat = _score_catalyst(metrics, indicator)
    sup = _score_supply_risk(metrics)
    exe = _score_execution(metrics, indicator)

    total = round(min(liq + ups + vol + struct + rs + volume + cat + sup + exe, 100.0), 2)
    category = _assign_category(total, metrics, indicator, config)
    prob = _prob_from_map(total, config.prob_map)

    return ScoreBreakdown(
        symbol=metrics.symbol,
        category=category,
        exclusion_reason=None,
        score_total=total,
        score_liquidity=round(liq, 2),
        score_upside=round(ups, 2),
        score_volatility=round(vol, 2),
        score_structure=round(struct, 2),
        score_rel_strength=round(rs, 2),
        score_volume=round(volume, 2),
        score_catalyst=round(cat, 2),
        score_supply_risk=round(sup, 2),
        score_execution=round(exe, 2),
        probability_pct=prob,
    )


def run_scoring_engine(
    filter_result: FilterResult,
    config: ScoringConfig | None = None,
) -> ScoringResult:
    """Score all assets that passed the hard filter.

    Iterates over co-indexed filter_result.passed_metrics and
    filter_result.passed_indicators. Output is sorted by score_total
    descending (best candidate first).

    Args:
        filter_result: FilterResult from run_hard_filter() (PR 7).
        config:        Scoring thresholds. Defaults to ScoringConfig() if None.

    Returns:
        ScoringResult with all ScoreBreakdowns sorted by score_total desc.
    """
    if config is None:
        config = ScoringConfig()

    total = filter_result.passed_count
    if total == 0:
        log.warning("run_scoring_engine called with zero assets")
        return ScoringResult()

    log.info("Stage 5 — scoring %d assets", total)

    scores: list[ScoreBreakdown] = []
    for metrics, indicator in zip(filter_result.passed_metrics, filter_result.passed_indicators):
        try:
            breakdown = score_asset(metrics, indicator, config)
            scores.append(breakdown)
            log.debug(
                "%s — score=%.1f  cat=%s  prob=%s",
                metrics.symbol,
                breakdown.score_total,
                breakdown.category,
                f"{breakdown.probability_pct:.0f}%" if breakdown.probability_pct else "n/a",
            )
        except Exception as exc:
            log.warning("%s — scoring failed: %s", metrics.symbol, exc)

    scores.sort(key=lambda s: s.score_total, reverse=True)
    result = ScoringResult(scores=scores)

    log.info(
        "Stage 5 complete — clean=%d ugly=%d watchlist=%d  (top: %s %.1f)",
        result.clean_count,
        result.ugly_count,
        len(result.watchlist),
        scores[0].symbol if scores else "—",
        scores[0].score_total if scores else 0.0,
    )
    return result
