"""Unit tests for scanner.selector — candidate selection and trade parameters.

All tests are offline. No DB, no HTTP.
compute_trade_parameters is tested against DB constraint requirements.
run_candidate_selector is tested end-to-end with synthetic scored candidates.
"""

from __future__ import annotations

import pytest

from scanner.models import (
    AssetIndicators,
    FilterResult,
    IndicatorSnapshot,
    MarketMetrics,
    ScoreBreakdown,
    ScoringResult,
)
from scanner.selector import (
    SelectorConfig,
    _assign_size_bucket,
    _build_notes,
    _compute_stop_pct,
    compute_trade_parameters,
    run_candidate_selector,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_CFG = SelectorConfig()


def _snap(
    rsi_14: float | None = 60.0,
    atr_14_pct: float | None = 8.0,
    price_vs_ema20_pct: float | None = 3.0,
    trend_state: str | None = "up",
    ema_alignment: str | None = "bullish",
    vwap_state: str | None = "above",
    volume_current: float | None = 1200.0,
    volume_ma_20: float | None = 1000.0,
    ema_20: float | None = None,
    ema_50: float | None = None,
    vwap: float | None = None,
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


def _indicator(symbol: str = "BTC", **kwargs: object) -> AssetIndicators:
    s = _snap(**kwargs)  # type: ignore[arg-type]
    return AssetIndicators(symbol=symbol, kraken_pair=f"{symbol}USD", tf_4h=s, tf_1h=s, tf_30m=s)


def _metrics(
    symbol: str = "BTC",
    price_usd: float = 50_000.0,
    atr_pct_7d: float | None = 8.0,
    dist_from_20d_high: float | None = -0.15,
    volume_7d_avg_usd: float | None = 8_000_000.0,
    volume_ratio_20d: float | None = 1.4,
    return_7d: float | None = 0.12,
    return_3d: float | None = 0.06,
) -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="",
        price_usd=price_usd,
        price_btc=None,
        volume_24h_usd=5_000_000.0,
        volume_7d_avg_usd=volume_7d_avg_usd,
        volume_ratio_20d=volume_ratio_20d,
        return_3d=return_3d,
        return_7d=return_7d,
        return_14d=0.18,
        return_vs_btc_7d=0.05,
        dist_from_7d_high=-0.10,
        dist_from_20d_high=dist_from_20d_high,
        spread_pct=0.008,
        atr_pct_7d=atr_pct_7d,
    )


def _score(symbol: str = "BTC", total: float = 76.0, category: str = "clean") -> ScoreBreakdown:
    return ScoreBreakdown(
        symbol=symbol,
        category=category,
        exclusion_reason=None,
        score_total=total,
        score_liquidity=14.0,
        score_upside=12.0,
        score_volatility=10.0,
        score_structure=13.0,
        score_rel_strength=8.0,
        score_volume=8.0,
        score_catalyst=8.0,
        score_supply_risk=4.0,
        score_execution=4.0,
        probability_pct=77.0,
    )


def _filter_result(
    pairs: list[tuple[MarketMetrics, AssetIndicators]] | None = None,
) -> FilterResult:
    pairs = pairs or [(_metrics("BTC"), _indicator("BTC"))]
    return FilterResult(
        passed_metrics=[p[0] for p in pairs],
        passed_indicators=[p[1] for p in pairs],
        exclusions=[],
    )


def _scoring_result_with(
    clean: list[tuple[str, float]] | None = None,
    ugly: list[tuple[str, float]] | None = None,
) -> ScoringResult:
    scores: list[ScoreBreakdown] = []
    for sym, total in clean or []:
        scores.append(_score(sym, total, "clean"))
    for sym, total in ugly or []:
        scores.append(_score(sym, total, "ugly"))
    return ScoringResult(scores=scores)


# ── _compute_stop_pct ─────────────────────────────────────────────────────────


def test_compute_stop_pct_clean_atr_based() -> None:
    pct = _compute_stop_pct("clean", 8.0, _CFG)
    expected = 8.0 / 100.0 * _CFG.clean_stop_atr_multiplier
    assert pct == pytest.approx(expected)


def test_compute_stop_pct_clean_clamped_to_max() -> None:
    pct = _compute_stop_pct("clean", 20.0, _CFG)  # 20% × 1.5 = 30% → clamped to 12%
    assert pct == pytest.approx(_CFG.clean_max_stop_pct)


def test_compute_stop_pct_ugly_respects_min() -> None:
    pct = _compute_stop_pct("ugly", 2.0, _CFG)  # 2% × 2.0 = 4% → clamped to ugly min 8%
    assert pct == pytest.approx(_CFG.ugly_min_stop_pct)


def test_compute_stop_pct_ugly_clamped_to_max() -> None:
    pct = _compute_stop_pct("ugly", 15.0, _CFG)  # 15% × 2.0 = 30% → clamped to 15%
    assert pct == pytest.approx(_CFG.ugly_max_stop_pct)


def test_compute_stop_pct_none_atr_returns_default() -> None:
    clean_pct = _compute_stop_pct("clean", None, _CFG)
    ugly_pct = _compute_stop_pct("ugly", None, _CFG)
    assert _CFG.clean_min_stop_pct <= clean_pct <= _CFG.clean_max_stop_pct
    assert _CFG.ugly_min_stop_pct <= ugly_pct <= _CFG.ugly_max_stop_pct


def test_ugly_stop_wider_than_clean() -> None:
    ugly_pct = _compute_stop_pct("ugly", 8.0, _CFG)
    clean_pct = _compute_stop_pct("clean", 8.0, _CFG)
    assert ugly_pct >= clean_pct


# ── _assign_size_bucket ───────────────────────────────────────────────────────


def test_size_bucket_clean_20k_plus() -> None:
    s = _score(total=83.0)
    m = _metrics(volume_7d_avg_usd=55_000_000)
    assert _assign_size_bucket(s, m, "clean") == "20k+"


def test_size_bucket_clean_10k_20k() -> None:
    s = _score(total=76.0)
    m = _metrics(volume_7d_avg_usd=22_000_000)
    assert _assign_size_bucket(s, m, "clean") == "10k-20k"


def test_size_bucket_clean_5k_10k() -> None:
    s = _score(total=72.0)
    m = _metrics(volume_7d_avg_usd=12_000_000)
    assert _assign_size_bucket(s, m, "clean") == "5k-10k"


def test_size_bucket_clean_default_2k_5k() -> None:
    s = _score(total=71.0)
    m = _metrics(volume_7d_avg_usd=1_000_000)  # too low for 5k-10k
    assert _assign_size_bucket(s, m, "clean") == "2k-5k"


def test_size_bucket_ugly_5k_10k() -> None:
    s = _score(total=71.0, category="ugly")
    m = _metrics(volume_7d_avg_usd=6_000_000)
    assert _assign_size_bucket(s, m, "ugly") == "5k-10k"


def test_size_bucket_ugly_2k_5k() -> None:
    s = _score(total=66.0, category="ugly")
    m = _metrics(volume_7d_avg_usd=1_000_000)
    assert _assign_size_bucket(s, m, "ugly") == "2k-5k"


def test_size_bucket_ugly_minimum_2k() -> None:
    s = _score(total=63.0, category="ugly")
    m = _metrics(volume_7d_avg_usd=800_000)
    assert _assign_size_bucket(s, m, "ugly") == "2k"


# ── compute_trade_parameters — DB constraint verification ─────────────────────


def test_trade_params_stop_below_entry() -> None:
    tp = compute_trade_parameters(_metrics(), _indicator(), _score(), "clean", _CFG)
    assert tp.stop_loss < tp.entry_price


def test_trade_params_exit_above_entry() -> None:
    tp = compute_trade_parameters(_metrics(), _indicator(), _score(), "clean", _CFG)
    assert tp.exit_price > tp.entry_price


def test_trade_params_entry_zone_ordered() -> None:
    tp = compute_trade_parameters(_metrics(), _indicator(), _score(), "clean", _CFG)
    assert tp.entry_price_low is not None
    assert tp.entry_price_high is not None
    assert tp.entry_price_low <= tp.entry_price_high


def test_trade_params_entry_high_below_current_price() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.entry_price_high < 100.0


def test_trade_params_rr_respects_clean_minimum() -> None:
    tp = compute_trade_parameters(_metrics(), _indicator(), _score(), "clean", _CFG)
    assert tp.reward_risk_ratio >= _CFG.clean_min_reward_risk - 0.01


def test_trade_params_rr_respects_ugly_minimum() -> None:
    ugly_score = _score("BTC", 65.0, "ugly")
    tp = compute_trade_parameters(_metrics(), _indicator(), ugly_score, "ugly", _CFG)
    assert tp.reward_risk_ratio >= _CFG.ugly_min_reward_risk - 0.01


def test_trade_params_technical_target_used_when_clear() -> None:
    """When price is 20 % below 20d high, technical target should exceed R:R minimum."""
    m = _metrics(price_usd=100.0, atr_pct_7d=8.0, dist_from_20d_high=-0.20)
    tp = compute_trade_parameters(m, _indicator(), _score(), "clean", _CFG)
    # 20d_high ≈ 100 / 0.80 = 125; tech_exit ≈ 125 * 0.97 = 121.25
    # min_rr_exit = 100 + 2.0 * (100 - stop)
    assert tp.exit_price > tp.entry_price * 1.05


def test_trade_params_expected_gain_pct_formula() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    expected = round((tp.exit_price - tp.entry_price) / tp.entry_price * 100, 4)
    assert tp.expected_gain_pct == pytest.approx(expected, rel=1e-4)


def test_trade_params_rr_formula() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    expected = round((tp.exit_price - tp.entry_price) / (tp.entry_price - tp.stop_loss), 3)
    assert tp.reward_risk_ratio == pytest.approx(expected, rel=1e-4)


def test_trade_params_size_bucket_populated() -> None:
    tp = compute_trade_parameters(_metrics(), _indicator(), _score(), "clean", _CFG)
    from scanner.models import SIZE_BUCKETS

    assert tp.suggested_size_bucket in SIZE_BUCKETS


def test_notes_string_contains_trend() -> None:
    ind = _indicator(trend_state="strong_up")
    notes = _build_notes(_metrics(), ind)
    assert "strong_up" in notes


def test_notes_string_contains_rsi() -> None:
    ind = _indicator(rsi_14=63.0)
    notes = _build_notes(_metrics(), ind)
    assert "rsi:63" in notes


# ── setup-aware entry fields ─────────────────────────────────────────────────


def test_trade_params_setup_type_is_pullback_by_default() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.setup_type == "pullback"


def test_trade_params_preferred_entry_equals_entry_price() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.preferred_entry == tp.entry_price


def test_trade_params_max_entry_equals_entry_price_high() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.max_entry == tp.entry_price_high


def test_trade_params_support_anchor_type_populated() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.support_anchor_type is not None


def test_trade_params_entry_below_current_price() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.entry_price < tp.current_price
    assert tp.entry_price_high < tp.current_price


def test_trade_params_distance_to_entry_is_negative() -> None:
    tp = compute_trade_parameters(_metrics(price_usd=100.0), _indicator(), _score(), "clean", _CFG)
    assert tp.distance_to_entry_pct < 0
    assert tp.current_price == pytest.approx(100.0)


# ── run_candidate_selector ────────────────────────────────────────────────────


def test_run_selector_empty_scoring() -> None:
    result = run_candidate_selector(ScoringResult(), FilterResult())
    assert result.total_count == 0
    assert result.clean == []
    assert result.ugly == []


def test_run_selector_rank_1_is_highest_score() -> None:
    pairs = [(_metrics(sym), _indicator(sym)) for sym in ["A", "B", "C"]]
    fr = _filter_result(pairs)
    sr = _scoring_result_with(clean=[("A", 80.0), ("B", 74.0), ("C", 71.0)])
    result = run_candidate_selector(sr, fr)
    assert result.clean[0].symbol == "A"
    assert result.clean[0].rank == 1
    assert result.clean[1].rank == 2


def test_run_selector_respects_max_candidates() -> None:
    pairs = [(_metrics(f"X{i}"), _indicator(f"X{i}")) for i in range(8)]
    fr = _filter_result(pairs)
    sr = _scoring_result_with(clean=[(f"X{i}", 80.0 - i) for i in range(8)])
    cfg = SelectorConfig(max_clean_candidates=3)
    result = run_candidate_selector(sr, fr, cfg)
    assert len(result.clean) == 3


def test_run_selector_symbols_match_filter_result() -> None:
    pairs = [(_metrics("SOL"), _indicator("SOL")), (_metrics("ETH"), _indicator("ETH"))]
    fr = _filter_result(pairs)
    sr = _scoring_result_with(clean=[("SOL", 78.0)], ugly=[("ETH", 65.0)])
    result = run_candidate_selector(sr, fr)
    assert result.clean[0].symbol == "SOL"
    assert result.ugly[0].symbol == "ETH"


def test_run_selector_all_candidates_aggregates() -> None:
    pairs = [(_metrics("A"), _indicator("A")), (_metrics("B"), _indicator("B"))]
    fr = _filter_result(pairs)
    sr = _scoring_result_with(clean=[("A", 75.0)], ugly=[("B", 65.0)])
    result = run_candidate_selector(sr, fr)
    assert result.total_count == 2
    syms = {c.symbol for c in result.all_candidates}
    assert syms == {"A", "B"}


# ── Validity gates (EntryEngineError → EntryRejection) ────────────────────────


def test_run_selector_captures_breakout_chase_rejection() -> None:
    """Breakout candidate above current_price × (1 + max_chase) is rejected,
    not in clean/ugly, and recorded as an EntryRejection with the chase-ceiling
    reason constant."""
    from scanner.rejection_reasons import ENTRY_REJECT_BREAKOUT_CHASE_CEILING

    # Breakout setup: dist_from_20d_high near 0, ret_7d > 8%, trend up.
    # Force preferred_entry well above current_price by placing price at/above 20d high.
    m = _metrics(
        "BO",
        price_usd=100.0,
        dist_from_20d_high=-0.02,  # approaching 20d high — triggers breakout-above-high path
        return_7d=0.15,
    )
    ind = _indicator("BO", trend_state="strong_up")
    fr = _filter_result(pairs=[(m, ind)])
    sr = _scoring_result_with(clean=[("BO", 80.0)])
    # Tighten the chase ceiling to make the rejection deterministic.
    cfg = SelectorConfig(max_chase_current_price_pct=0.0)
    result = run_candidate_selector(sr, fr, cfg)

    assert result.clean == []
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej.symbol == "BO"
    assert rej.category == "clean"
    assert rej.setup_type == "breakout_trigger"
    assert rej.rejection_reason == ENTRY_REJECT_BREAKOUT_CHASE_CEILING
    assert rej.metadata["score_total"] == 80.0
    assert rej.metadata["current_price"] == pytest.approx(100.0)


def test_run_selector_captures_reclaim_no_anchor_rejection() -> None:
    """Reclaim setup with no qualified anchor in proximity window is rejected
    with the no-anchor reason constant."""
    from scanner.rejection_reasons import ENTRY_REJECT_NO_QUALIFIED_ANCHOR

    # Reclaim triggers when price_vs_ema20_pct in [-3, 4] and ret_3d>0 and
    # ret_7d in [-12%, 8%]. Provide no usable EMA-20 or VWAP values so the
    # anchor search returns nothing.
    m = _metrics("RC", price_usd=50.0, return_7d=0.02, return_3d=0.01)
    ind = _indicator(
        "RC",
        price_vs_ema20_pct=1.0,  # within reclaim band
        trend_state="up",
        ema_20=None,
        vwap=None,
    )
    fr = _filter_result(pairs=[(m, ind)])
    sr = _scoring_result_with(clean=[("RC", 75.0)])
    result = run_candidate_selector(sr, fr)

    assert result.clean == []
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej.rejection_reason == ENTRY_REJECT_NO_QUALIFIED_ANCHOR
    assert rej.setup_type == "reclaim"


def test_run_selector_rejected_not_double_counted_in_total() -> None:
    """SelectionResult.total_count counts only accepted candidates."""
    m = _metrics("BO", price_usd=100.0, dist_from_20d_high=-0.02, return_7d=0.15)
    ind = _indicator("BO", trend_state="strong_up")
    fr = _filter_result(pairs=[(m, ind)])
    sr = _scoring_result_with(clean=[("BO", 80.0)])
    cfg = SelectorConfig(max_chase_current_price_pct=0.0)
    result = run_candidate_selector(sr, fr, cfg)
    assert len(result.rejected) == 1
    assert result.total_count == 0
    assert result.all_candidates == []


# ── Table-driven DB-invariant coverage over varied inputs ─────────────────────


_INVARIANT_CASES = [
    # (label, price_usd, atr_pct_7d, dist_from_20d_high, return_7d, return_3d, category)
    ("baseline_clean", 50_000.0, 8.0, -0.15, 0.12, 0.06, "clean"),
    ("low_atr_clean", 100.0, 3.0, -0.10, 0.08, 0.04, "clean"),
    ("high_atr_clean", 100.0, 17.0, -0.25, 0.10, 0.05, "clean"),
    ("at_atr_floor_clean", 25.0, 2.5, -0.18, 0.07, 0.03, "clean"),
    ("deep_below_20d_high", 100.0, 8.0, -0.30, 0.06, 0.02, "clean"),
    ("near_20d_high_clean", 100.0, 6.0, -0.05, 0.05, 0.02, "clean"),
    ("baseline_ugly", 5.0, 12.0, -0.20, 0.18, 0.10, "ugly"),
    ("high_atr_ugly", 0.50, 22.0, -0.25, 0.20, 0.12, "ugly"),
    ("low_price_ugly", 0.001, 15.0, -0.18, 0.15, 0.08, "ugly"),
]


@pytest.mark.parametrize(
    "label, price_usd, atr_pct_7d, dist_from_20d_high, return_7d, return_3d, category",
    _INVARIANT_CASES,
    ids=[c[0] for c in _INVARIANT_CASES],
)
def test_trade_params_invariants_table(
    label: str,
    price_usd: float,
    atr_pct_7d: float,
    dist_from_20d_high: float,
    return_7d: float,
    return_3d: float,
    category: str,
) -> None:
    """DB ordering invariants must hold for every accepted candidate across a
    range of price scales, ATR magnitudes, and 20d-high distances.

    `stop_loss < entry_price < exit_price` and `entry_price_low <= entry_price_high`
    are guarantees of compute_trade_parameters; this test pins them across
    realistic input variation, not just the baseline fixture.

    Inputs are tuned so classify_setup() returns 'pullback' for every row
    (price_vs_ema20_pct=8 keeps us out of the reclaim band; dist_from_20d_high
    < -3% keeps us out of the breakout band). An EMA-20 anchor is provided
    so the pullback path always finds a qualified support level.
    """
    m = _metrics(
        symbol="X",
        price_usd=price_usd,
        atr_pct_7d=atr_pct_7d,
        dist_from_20d_high=dist_from_20d_high,
        return_7d=return_7d,
        return_3d=return_3d,
    )
    # EMA-20 anchor at 92% of price — qualifies as pullback support
    # (>= min_pullback_discount of 2%) regardless of price scale.
    ind = _indicator(
        "X",
        price_vs_ema20_pct=8.0,
        ema_20=price_usd * 0.92,
    )
    score = _score("X", 75.0 if category == "clean" else 65.0, category)
    tp = compute_trade_parameters(m, ind, score, category, _CFG)
    assert tp.stop_loss < tp.entry_price, f"{label}: stop >= entry"
    assert tp.exit_price > tp.entry_price, f"{label}: exit <= entry"
    assert tp.entry_price_low is not None
    assert tp.entry_price_high is not None
    assert tp.entry_price_low <= tp.entry_price_high, f"{label}: zone inverted"
    assert tp.exit_price >= tp.entry_price * 1.05 - 1e-6, f"{label}: below 5% floor"
