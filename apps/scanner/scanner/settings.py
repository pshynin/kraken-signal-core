"""Strategy Settings Loader — PR 12.

Fetches runtime-configurable thresholds from the strategy_settings Supabase
table and converts them to the per-stage config dataclasses used throughout
the scanner pipeline.

The strategy_settings table is a flat key-value store (setting_key TEXT,
setting_value TEXT). All parsing is done in Python; missing keys fall back
to the StrategySettings default values, which match migration 0012 seed data.

Public API:
    load_strategy_settings(client) -> StrategySettings
    default_settings()             -> StrategySettings

Converters on StrategySettings:
    .to_hard_filter_config()   -> HardFilterConfig   (scanner Stage 4)
    .to_scoring_config()       -> ScoringConfig       (scanner Stage 5)
    .to_selector_config()      -> SelectorConfig      (scanner Stage 6)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from supabase import Client

if TYPE_CHECKING:
    from scanner.filter import HardFilterConfig
    from scanner.scoring import ScoringConfig
    from scanner.selector import SelectorConfig

log = logging.getLogger(__name__)

# ── Default probability map (matches migration 0012 scoring.probability_map) ──
_DEFAULT_PROB_MAP: tuple[tuple[float, float], ...] = (
    (85.0, 90.0),
    (78.0, 84.0),
    (70.0, 77.0),
    (62.0, 69.0),
)


# ── Settings dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategySettings:
    """Unified strategy settings loaded from the strategy_settings table.

    All defaults match migration 0012 seed values. Any key absent from the
    DB row falls back to the corresponding Python default here, so the scanner
    is safe to run against an empty strategy_settings table.

    Converter methods produce the per-stage config dataclasses accepted by
    run_hard_filter(), run_scoring_engine(), and run_candidate_selector().
    """

    # ── Global hard-exclusion ─────────────────────────────────────────────────
    rsi_hard_min: float = 42.0
    """global.rsi_hard_min — RSI below this → hard exclude asset."""
    rsi_hard_max: float = 78.0
    """global.rsi_hard_max — RSI above this → hard exclude asset."""

    # ── Clean thresholds ──────────────────────────────────────────────────────
    clean_min_score: float = 70.0
    """clean.min_score — minimum total score for clean category."""
    clean_min_volume_7d_avg_usd: float = 5_000_000.0
    """clean.min_volume_7d_avg_usd — 7d avg volume floor for clean ($5M)."""
    clean_min_volume_24h_usd: float = 2_000_000.0
    """clean.min_volume_24h_usd — 24h volume floor for clean ($2M)."""
    clean_min_atr_pct: float = 2.5
    """clean.min_atr_pct — ATR % floor for clean (lowest hard-filter floor)."""
    clean_max_atr_pct: float = 18.0
    """clean.max_atr_pct — ATR % ceiling for clean."""
    clean_max_return_3d: float = 0.30
    """clean.max_return_3d — anti-chase 3d return ceiling for clean (30%)."""
    clean_max_price_vs_ema20_pct: float = 12.0
    """clean.max_price_vs_ema20_pct — anti-chase EMA20 ceiling for clean (12%)."""
    clean_min_volume_ratio: float = 1.2
    """clean.min_volume_ratio — volume expansion ratio vs 20d MA."""
    clean_require_positive_rs_btc: bool = True
    """clean.require_positive_rs_btc — must have positive RS vs BTC."""
    clean_max_entry_distance_pct: float = 5.0
    """clean.max_entry_distance_pct — entry must be within 5% of current price."""
    clean_min_reward_risk: float = 2.0
    """clean.min_reward_risk — minimum R:R for clean trade parameters."""
    clean_rsi_preferred_min: float = 52.0
    """clean.rsi_preferred_min — RSI preferred lower bound for clean."""
    clean_rsi_preferred_max: float = 68.0
    """clean.rsi_preferred_max — RSI preferred upper bound for clean."""

    # ── Ugly thresholds ───────────────────────────────────────────────────────
    ugly_min_score: float = 62.0
    """ugly.min_score — minimum total score for ugly category."""
    ugly_min_volume_7d_avg_usd: float = 750_000.0
    """ugly.min_volume_7d_avg_usd — 7d avg volume floor for ugly ($750k)."""
    ugly_min_volume_24h_usd: float = 300_000.0
    """ugly.min_volume_24h_usd — 24h volume floor for ugly ($300k)."""
    ugly_min_atr_pct: float = 6.0
    """ugly.min_atr_pct — ATR % floor for ugly."""
    ugly_max_atr_pct: float = 30.0
    """ugly.max_atr_pct — ATR % ceiling for ugly (highest hard-filter ceiling)."""
    ugly_max_return_3d: float = 0.40
    """ugly.max_return_3d — anti-chase 3d return ceiling for ugly (40%)."""
    ugly_max_price_vs_ema20_pct: float = 20.0
    """ugly.max_price_vs_ema20_pct — anti-chase EMA20 ceiling for ugly (20%)."""
    ugly_min_volume_ratio: float = 1.3
    """ugly.min_volume_ratio — volume expansion ratio vs 20d MA."""
    ugly_min_stop_pct: float = 8.0
    """ugly.min_stop_pct — stored as % (8.0 = 8%). to_selector_config divides by 100."""
    ugly_max_stop_pct: float = 15.0
    """ugly.max_stop_pct — stored as % (15.0 = 15%). to_selector_config divides by 100."""
    ugly_min_reward_risk: float = 2.5
    """ugly.min_reward_risk — minimum R:R for ugly trade parameters."""
    ugly_rsi_preferred_min: float = 50.0
    """ugly.rsi_preferred_min — RSI preferred lower bound for ugly."""
    ugly_rsi_preferred_max: float = 72.0
    """ugly.rsi_preferred_max — RSI preferred upper bound for ugly."""

    # ── Scanner behavior ──────────────────────────────────────────────────────
    scanner_max_clean_candidates: int = 10
    """scanner.max_clean_candidates — top-N clean output."""
    scanner_max_ugly_candidates: int = 10
    """scanner.max_ugly_candidates — top-N ugly output."""
    scanner_min_score_delta_for_rotation: float = 3.0
    """scanner.min_score_delta_for_rotation — stability rule for candidate rotation."""
    scanner_alert_dedup_hours: int = 24
    """scanner.alert_dedup_hours — recency window (hours) for New vs Updated.

    A coin alerted within this window shows as Updated (with a price delta);
    otherwise New. Does not suppress alerts. (Key name retained for DB/UI
    compatibility; semantics repurposed from the original dedup window.)
    """
    scanner_stale_run_threshold_hours: int = 6
    """scanner.stale_run_threshold_hours — hours before stale-run system alert fires."""
    scanner_min_trade_size_usd: float = 2000.0
    """scanner.min_trade_size_usd — minimum practical trade size ($)."""
    scanner_run_timeout_minutes: int = 120
    """scanner.run_timeout_minutes — minutes before a stuck running row is timed_out."""

    # ── Probability map ───────────────────────────────────────────────────────
    prob_map: tuple[tuple[float, float], ...] = _DEFAULT_PROB_MAP
    """Score-floor → probability-pct tiers. Sorted descending by floor.
    Loaded from scoring.probability_map JSON in strategy_settings.
    """

    # ── Config converters ─────────────────────────────────────────────────────

    def to_hard_filter_config(self) -> HardFilterConfig:
        """Build HardFilterConfig using most-permissive cross-category thresholds.

        The hard filter uses the most lenient threshold across clean + ugly so
        only assets that cannot qualify for either category are excluded here.
        Per-category tightening happens in the scoring engine.

            Volume floors   → ugly (lower)
            RSI bounds      → global
            Return ceiling  → ugly (higher, 40%)
            EMA20 ceiling   → ugly (higher, 20%)
            ATR floor       → clean (lower, 4%)
            ATR ceiling     → ugly  (higher, 30%)
        """
        from scanner.filter import HardFilterConfig

        return HardFilterConfig(
            min_volume_24h_usd=self.ugly_min_volume_24h_usd,
            min_volume_7d_avg_usd=self.ugly_min_volume_7d_avg_usd,
            rsi_hard_min=self.rsi_hard_min,
            rsi_hard_max=self.rsi_hard_max,
            max_return_3d=self.ugly_max_return_3d,
            max_price_vs_ema20_pct=self.ugly_max_price_vs_ema20_pct,
            min_atr_pct=self.clean_min_atr_pct,
            max_atr_pct=self.ugly_max_atr_pct,
        )

    def to_scoring_config(self) -> ScoringConfig:
        """Build ScoringConfig for the scoring engine (Stage 5)."""
        from scanner.scoring import ScoringConfig

        return ScoringConfig(
            clean_min_score=self.clean_min_score,
            clean_min_volume_24h_usd=self.clean_min_volume_24h_usd,
            clean_min_volume_7d_avg_usd=self.clean_min_volume_7d_avg_usd,
            clean_rsi_preferred_min=self.clean_rsi_preferred_min,
            clean_rsi_preferred_max=self.clean_rsi_preferred_max,
            clean_max_return_3d=self.clean_max_return_3d,
            clean_max_price_vs_ema20_pct=self.clean_max_price_vs_ema20_pct,
            ugly_min_score=self.ugly_min_score,
            ugly_rsi_preferred_min=self.ugly_rsi_preferred_min,
            ugly_rsi_preferred_max=self.ugly_rsi_preferred_max,
            prob_map=self.prob_map,
        )

    def to_selector_config(self) -> SelectorConfig:
        """Build SelectorConfig for the candidate selector (Stage 6).

        ugly_min/max_stop_pct are stored as percentages in StrategySettings
        (DB value 8.0 = 8%) but SelectorConfig expects fractions (0.08).
        """
        from scanner.selector import SelectorConfig

        return SelectorConfig(
            max_clean_candidates=self.scanner_max_clean_candidates,
            max_ugly_candidates=self.scanner_max_ugly_candidates,
            clean_min_reward_risk=self.clean_min_reward_risk,
            ugly_min_stop_pct=self.ugly_min_stop_pct / 100.0,
            ugly_max_stop_pct=self.ugly_max_stop_pct / 100.0,
            ugly_min_reward_risk=self.ugly_min_reward_risk,
        )


# ── Parsing helpers ───────────────────────────────────────────────────────────


def _f(raw: dict[str, str], key: str, default: float) -> float:
    v = raw.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        log.warning("settings: invalid float for %s=%r — using default %.4g", key, v, default)
        return default


def _i(raw: dict[str, str], key: str, default: int) -> int:
    v = raw.get(key)
    if v is None:
        return default
    try:
        return int(float(v))  # "8.0" → 8
    except (ValueError, TypeError):
        log.warning("settings: invalid int for %s=%r — using default %d", key, v, default)
        return default


def _b(raw: dict[str, str], key: str, default: bool) -> bool:
    v = raw.get(key)
    if v is None:
        return default
    return v.strip().lower() == "true"


def _parse_prob_map(raw: dict[str, str]) -> tuple[tuple[float, float], ...]:
    v = raw.get("scoring.probability_map")
    if not v:
        return _DEFAULT_PROB_MAP
    try:
        data: dict[str, Any] = json.loads(v)
        pairs = sorted(
            [(float(k), float(pct)) for k, pct in data.items()],
            key=lambda x: x[0],
            reverse=True,
        )
        return tuple(pairs) if pairs else _DEFAULT_PROB_MAP
    except Exception as exc:
        log.warning("settings: failed to parse scoring.probability_map: %s", exc)
        return _DEFAULT_PROB_MAP


def _parse_settings_dict(raw: dict[str, str]) -> StrategySettings:
    """Build StrategySettings from a {setting_key: setting_value} dict."""
    return StrategySettings(
        rsi_hard_min=_f(raw, "global.rsi_hard_min", 42.0),
        rsi_hard_max=_f(raw, "global.rsi_hard_max", 78.0),
        clean_min_score=_f(raw, "clean.min_score", 70.0),
        clean_min_volume_7d_avg_usd=_f(raw, "clean.min_volume_7d_avg_usd", 5_000_000.0),
        clean_min_volume_24h_usd=_f(raw, "clean.min_volume_24h_usd", 2_000_000.0),
        clean_min_atr_pct=_f(raw, "clean.min_atr_pct", 2.5),
        clean_max_atr_pct=_f(raw, "clean.max_atr_pct", 18.0),
        clean_max_return_3d=_f(raw, "clean.max_return_3d", 0.30),
        clean_max_price_vs_ema20_pct=_f(raw, "clean.max_price_vs_ema20_pct", 12.0),
        clean_min_volume_ratio=_f(raw, "clean.min_volume_ratio", 1.2),
        clean_require_positive_rs_btc=_b(raw, "clean.require_positive_rs_btc", True),
        clean_max_entry_distance_pct=_f(raw, "clean.max_entry_distance_pct", 5.0),
        clean_min_reward_risk=_f(raw, "clean.min_reward_risk", 2.0),
        clean_rsi_preferred_min=_f(raw, "clean.rsi_preferred_min", 52.0),
        clean_rsi_preferred_max=_f(raw, "clean.rsi_preferred_max", 68.0),
        ugly_min_score=_f(raw, "ugly.min_score", 62.0),
        ugly_min_volume_7d_avg_usd=_f(raw, "ugly.min_volume_7d_avg_usd", 750_000.0),
        ugly_min_volume_24h_usd=_f(raw, "ugly.min_volume_24h_usd", 300_000.0),
        ugly_min_atr_pct=_f(raw, "ugly.min_atr_pct", 6.0),
        ugly_max_atr_pct=_f(raw, "ugly.max_atr_pct", 30.0),
        ugly_max_return_3d=_f(raw, "ugly.max_return_3d", 0.40),
        ugly_max_price_vs_ema20_pct=_f(raw, "ugly.max_price_vs_ema20_pct", 20.0),
        ugly_min_volume_ratio=_f(raw, "ugly.min_volume_ratio", 1.3),
        ugly_min_stop_pct=_f(raw, "ugly.min_stop_pct", 8.0),
        ugly_max_stop_pct=_f(raw, "ugly.max_stop_pct", 15.0),
        ugly_min_reward_risk=_f(raw, "ugly.min_reward_risk", 2.5),
        ugly_rsi_preferred_min=_f(raw, "ugly.rsi_preferred_min", 50.0),
        ugly_rsi_preferred_max=_f(raw, "ugly.rsi_preferred_max", 72.0),
        scanner_max_clean_candidates=_i(raw, "scanner.max_clean_candidates", 10),
        scanner_max_ugly_candidates=_i(raw, "scanner.max_ugly_candidates", 10),
        scanner_min_score_delta_for_rotation=_f(raw, "scanner.min_score_delta_for_rotation", 3.0),
        scanner_alert_dedup_hours=_i(raw, "scanner.alert_dedup_hours", 24),
        scanner_stale_run_threshold_hours=_i(raw, "scanner.stale_run_threshold_hours", 6),
        scanner_min_trade_size_usd=_f(raw, "scanner.min_trade_size_usd", 2000.0),
        scanner_run_timeout_minutes=_i(raw, "scanner.run_timeout_minutes", 120),
        prob_map=_parse_prob_map(raw),
    )


# ── Public API ────────────────────────────────────────────────────────────────


def default_settings() -> StrategySettings:
    """Return StrategySettings with all migration 0012 seed values.

    Used in dry-run mode and as the fallback when Supabase is unavailable.
    Equivalent to StrategySettings(), but named for clarity at call sites.
    """
    return StrategySettings()


def load_strategy_settings(client: Client) -> StrategySettings:
    """Fetch strategy_settings from Supabase and return a StrategySettings instance.

    Fetches all rows from the strategy_settings table, builds a raw {key: value}
    dict, and parses each field. Keys absent from the DB fall back to the
    StrategySettings defaults (migration 0012 seed values).

    Args:
        client: Authenticated Supabase client from scanner.db.get_client().

    Returns:
        StrategySettings with values from DB (missing keys → defaults).

    Raises:
        Exception: Propagates any Supabase client errors. Callers should
                   catch and fall back to default_settings().
    """
    resp = client.table("strategy_settings").select("setting_key, setting_value").execute()
    rows = cast(list[dict[str, Any]], resp.data or [])
    raw: dict[str, str] = {
        str(row["setting_key"]): (
            json.dumps(row["setting_value"])
            if isinstance(row["setting_value"], (dict, list))
            else str(row["setting_value"])
        )
        for row in rows
        if row.get("setting_key") and row.get("setting_value") is not None
    }
    settings = _parse_settings_dict(raw)
    log.info("strategy_settings: %d keys loaded from DB", len(raw))
    return settings
