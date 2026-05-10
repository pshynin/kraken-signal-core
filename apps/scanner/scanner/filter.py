"""Hard Filter — PR 7.

Applies hard exclusion rules to every asset using its MarketMetrics and
4h IndicatorSnapshot. Assets failing any rule are excluded from all
subsequent pipeline stages (scoring, candidate selection, alerts).

Public API:
    run_hard_filter(
        bundles:    list[AssetOHLCV],
        indicators: list[AssetIndicators],
        config:     HardFilterConfig | None = None,
    ) -> FilterResult

Internal API (exposed for unit testing):
    apply_hard_filter(metrics, indicator, config) -> HardFilterResult

Hard filter philosophy:
    Rules use the most-permissive threshold across clean + ugly categories.
    Only assets that cannot possibly qualify for EITHER category are excluded.
    Per-category filtering (clean.min_volume_7d = $5M vs ugly = $750k) happens
    in the scoring engine (PR 8) via score penalties.

Default thresholds match migration 0012 seed values (strategy_settings table).
In a future PR these will be loaded from Supabase at startup.

Exclusion reasons (for HardFilterResult.exclusion_reason):
    invalid_price           — price_usd <= 0
    insufficient_volume_24h — volume_24h_usd < 300,000
    insufficient_volume_7d  — volume_7d_avg_usd < 750,000
    rsi_below_hard_min      — rsi_14 < 48   (global.rsi_hard_min)
    rsi_above_hard_max      — rsi_14 > 78   (global.rsi_hard_max)
    extreme_pump_3d         — return_3d > 40% (anti-chase; ugly.max_return_3d)
    overextended_vs_ema20   — price_vs_ema20_pct > 20% (anti-chase; ugly threshold)
    insufficient_volatility — atr_pct_7d < 4.0% (clean.min_atr_pct, lowest floor)
    excessive_volatility    — atr_pct_7d > 30%  (ugly.max_atr_pct, highest ceiling)
    no_indicator            — AssetIndicators not found (indicator engine failed)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scanner.metrics import compute_market_metrics
from scanner.models import (
    AssetIndicators,
    AssetOHLCV,
    FilterResult,
    HardFilterResult,
    MarketMetrics,
)

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HardFilterConfig:
    """Hard-exclusion thresholds. Defaults match migration 0012 seed values.

    All values use the most permissive threshold across clean + ugly
    categories: only exclude assets that cannot qualify for either.
    """

    min_volume_24h_usd: float = 300_000.0
    """ugly.min_volume_24h_usd — most permissive 24h volume floor."""

    min_volume_7d_avg_usd: float = 750_000.0
    """ugly.min_volume_7d_avg_usd — most permissive 7d average volume floor."""

    rsi_hard_min: float = 48.0
    """global.rsi_hard_min — hard RSI lower bound."""

    rsi_hard_max: float = 78.0
    """global.rsi_hard_max — hard RSI upper bound."""

    max_return_3d: float = 0.40
    """ugly.max_return_3d — most permissive anti-chase return ceiling."""

    max_price_vs_ema20_pct: float = 20.0
    """ugly.max_price_vs_ema20_pct — most permissive anti-chase EMA20 ceiling."""

    min_atr_pct: float = 2.5
    """clean.min_atr_pct — lowest ATR floor across both categories."""

    max_atr_pct: float = 30.0
    """ugly.max_atr_pct — highest ATR ceiling across both categories."""


# ── Rule engine ───────────────────────────────────────────────────────────────


def apply_hard_filter(
    metrics: MarketMetrics,
    indicator: AssetIndicators,
    config: HardFilterConfig,
) -> HardFilterResult:
    """Evaluate hard exclusion rules for one asset. Returns on first match.

    Rules are checked in priority order. An asset failing any single rule
    is excluded immediately; subsequent rules are not evaluated.

    Args:
        metrics:   MarketMetrics from compute_market_metrics().
        indicator: AssetIndicators from run_indicator_engine().
        config:    Threshold configuration (defaults match migration 0012).

    Returns:
        HardFilterResult with passed=True and exclusion_reason=None
        if all rules clear, or passed=False with the first failing rule name.
    """
    snap = indicator.tf_4h
    sym = metrics.symbol

    def _reject(reason: str) -> HardFilterResult:
        log.debug("%s excluded: %s", sym, reason)
        return HardFilterResult(symbol=sym, passed=False, exclusion_reason=reason)

    # ── Rule 1: Valid price ────────────────────────────────────────────────────
    if metrics.price_usd <= 0:
        return _reject("invalid_price")

    # ── Rule 2: 24h volume floor ───────────────────────────────────────────────
    if metrics.volume_24h_usd is None or metrics.volume_24h_usd < config.min_volume_24h_usd:
        return _reject("insufficient_volume_24h")

    # ── Rule 3: 7-day average volume floor ────────────────────────────────────
    if (
        metrics.volume_7d_avg_usd is None
        or metrics.volume_7d_avg_usd < config.min_volume_7d_avg_usd
    ):
        return _reject("insufficient_volume_7d")

    # ── Rule 4 & 5: RSI hard bounds ────────────────────────────────────────────
    rsi = snap.rsi_14
    if rsi is not None:
        if rsi < config.rsi_hard_min:
            return _reject("rsi_below_hard_min")
        if rsi > config.rsi_hard_max:
            return _reject("rsi_above_hard_max")

    # ── Rule 6: Anti-chase — extreme 3-day pump ───────────────────────────────
    if metrics.return_3d is not None and metrics.return_3d > config.max_return_3d:
        return _reject("extreme_pump_3d")

    # ── Rule 7: Anti-chase — price overextended above EMA20 ───────────────────
    pve20 = snap.price_vs_ema20_pct
    if pve20 is not None and pve20 > config.max_price_vs_ema20_pct:
        return _reject("overextended_vs_ema20")

    # ── Rule 8 & 9: ATR volatility bounds ─────────────────────────────────────
    atr = metrics.atr_pct_7d
    if atr is not None:
        if atr < config.min_atr_pct:
            return _reject("insufficient_volatility")
        if atr > config.max_atr_pct:
            return _reject("excessive_volatility")

    return HardFilterResult(symbol=sym, passed=True, exclusion_reason=None)


# ── Pipeline entry point ──────────────────────────────────────────────────────


def run_hard_filter(
    bundles: list[AssetOHLCV],
    indicators: list[AssetIndicators],
    config: HardFilterConfig | None = None,
) -> FilterResult:
    """Compute market metrics and apply hard filter for all assets.

    Matches each bundle to its AssetIndicators by symbol. Bundles without
    a matching indicator (indicator computation failed in Stage 3) are
    excluded with reason 'no_indicator'.

    Args:
        bundles:    AssetOHLCV list from fetch_market_data() (PR 5).
        indicators: AssetIndicators list from run_indicator_engine() (PR 6).
        config:     Filter thresholds. Defaults to HardFilterConfig() if None.

    Returns:
        FilterResult with passed_metrics, passed_indicators (co-indexed),
        and exclusions.
    """
    if config is None:
        config = HardFilterConfig()

    if not bundles:
        log.warning("run_hard_filter called with empty bundle list")
        return FilterResult()

    # ── Build indicator lookup ─────────────────────────────────────────────────
    indicator_by_symbol: dict[str, AssetIndicators] = {ind.symbol: ind for ind in indicators}

    # ── Find BTC 7-day return for relative strength ────────────────────────────
    btc_return_7d: float | None = None
    if "BTC" in indicator_by_symbol:
        from scanner.metrics import _safe_return

        btc_bundle = next((b for b in bundles if b.symbol == "BTC"), None)
        if btc_bundle and btc_bundle.candles_4h:
            import pandas as pd

            btc_closes = pd.Series([c.close for c in btc_bundle.candles_4h], dtype=float)
            from scanner.metrics import CANDLES_7D

            btc_return_7d = _safe_return(btc_closes, CANDLES_7D)

    # ── Compute metrics + apply filter ─────────────────────────────────────────
    total = len(bundles)
    passed_metrics: list[MarketMetrics] = []
    passed_indicators: list[AssetIndicators] = []
    exclusions: list[HardFilterResult] = []

    log.info("Stage 4 — computing metrics + hard filter for %d assets", total)

    for bundle in bundles:
        indicator = indicator_by_symbol.get(bundle.symbol)

        if indicator is None:
            exclusions.append(
                HardFilterResult(
                    symbol=bundle.symbol,
                    passed=False,
                    exclusion_reason="no_indicator",
                )
            )
            continue

        metrics = compute_market_metrics(bundle, indicator, btc_return_7d)
        result = apply_hard_filter(metrics, indicator, config)

        if result.passed:
            passed_metrics.append(metrics)
            passed_indicators.append(indicator)
        else:
            exclusions.append(result)

    filter_result = FilterResult(
        passed_metrics=passed_metrics,
        passed_indicators=passed_indicators,
        exclusions=exclusions,
    )
    log.info(
        "Stage 4 complete — %d/%d passed (%.0f%%), %d excluded",
        filter_result.passed_count,
        total,
        filter_result.pass_rate * 100,
        filter_result.excluded_count,
    )
    if exclusions:
        reasons: dict[str, int] = {}
        for exc in exclusions:
            r = exc.exclusion_reason or "unknown"
            reasons[r] = reasons.get(r, 0) + 1
        log.info("Exclusion breakdown: %s", reasons)

    return filter_result
