"""Unit tests for scanner.settings — strategy settings loader.

All tests are offline: Supabase client replaced with MagicMock.
Tests verify parsing, fallback behaviour, converter correctness,
and that DB errors are handled gracefully.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.settings import (
    _DEFAULT_PROB_MAP,
    StrategySettings,
    _b,
    _f,
    _i,
    _parse_prob_map,
    _parse_settings_dict,
    default_settings,
    load_strategy_settings,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _client(rows: list[dict] | None = None) -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.data = rows or []
    client.table.return_value.select.return_value.execute.return_value = resp
    return client


def _seed_rows() -> list[dict]:
    """A representative subset of migration 0012 seed rows."""
    return [
        {"setting_key": "global.rsi_hard_min", "setting_value": "48"},
        {"setting_key": "global.rsi_hard_max", "setting_value": "78"},
        {"setting_key": "clean.min_score", "setting_value": "70"},
        {"setting_key": "clean.min_volume_7d_avg_usd", "setting_value": "5000000"},
        {"setting_key": "clean.min_volume_24h_usd", "setting_value": "2000000"},
        {"setting_key": "clean.min_atr_pct", "setting_value": "4.0"},
        {"setting_key": "clean.max_atr_pct", "setting_value": "18.0"},
        {"setting_key": "clean.min_reward_risk", "setting_value": "2.0"},
        {"setting_key": "ugly.min_score", "setting_value": "62"},
        {"setting_key": "ugly.min_volume_7d_avg_usd", "setting_value": "750000"},
        {"setting_key": "ugly.min_volume_24h_usd", "setting_value": "300000"},
        {"setting_key": "ugly.max_atr_pct", "setting_value": "30.0"},
        {"setting_key": "ugly.min_stop_pct", "setting_value": "8.0"},
        {"setting_key": "ugly.max_stop_pct", "setting_value": "15.0"},
        {"setting_key": "ugly.min_reward_risk", "setting_value": "2.5"},
        {"setting_key": "scanner.max_clean_candidates", "setting_value": "10"},
        {"setting_key": "scanner.max_ugly_candidates", "setting_value": "10"},
        {
            "setting_key": "scoring.probability_map",
            "setting_value": '{"85": 90.0, "78": 84.0, "70": 77.0, "62": 69.0}',
        },
    ]


# ── default_settings ──────────────────────────────────────────────────────────


def test_default_settings_returns_strategy_settings_instance() -> None:
    s = default_settings()
    assert isinstance(s, StrategySettings)


def test_default_settings_rsi_hard_min_matches_migration() -> None:
    assert default_settings().rsi_hard_min == 48.0


def test_default_settings_ugly_volume_24h_matches_migration() -> None:
    assert default_settings().ugly_min_volume_24h_usd == 300_000.0


# ── _parse_settings_dict ──────────────────────────────────────────────────────


def test_parse_settings_dict_overrides_rsi_hard_min() -> None:
    s = _parse_settings_dict({"global.rsi_hard_min": "45"})
    assert s.rsi_hard_min == 45.0


def test_parse_settings_dict_falls_back_on_empty() -> None:
    s = _parse_settings_dict({})
    assert s == default_settings()


def test_parse_settings_dict_handles_invalid_float_gracefully() -> None:
    s = _parse_settings_dict({"global.rsi_hard_min": "NOT_A_NUMBER"})
    assert s.rsi_hard_min == 48.0  # falls back to default


def test_parse_settings_dict_parses_int_as_float_string() -> None:
    s = _parse_settings_dict({"scanner.max_clean_candidates": "7.0"})
    assert s.scanner_max_clean_candidates == 7


# ── _parse_prob_map ───────────────────────────────────────────────────────────


def test_parse_prob_map_returns_sorted_descending() -> None:
    raw = {"scoring.probability_map": '{"62": 69.0, "85": 90.0, "70": 77.0, "78": 84.0}'}
    result = _parse_prob_map(raw)
    floors = [r[0] for r in result]
    assert floors == sorted(floors, reverse=True)


def test_parse_prob_map_fallback_on_missing_key() -> None:
    assert _parse_prob_map({}) == _DEFAULT_PROB_MAP


def test_parse_prob_map_fallback_on_invalid_json() -> None:
    assert _parse_prob_map({"scoring.probability_map": "{bad json"}) == _DEFAULT_PROB_MAP


# ── load_strategy_settings ────────────────────────────────────────────────────


def test_load_strategy_settings_parses_db_rows() -> None:
    client = _client(_seed_rows())
    s = load_strategy_settings(client)
    assert s.rsi_hard_min == 48.0
    assert s.clean_min_score == 70.0
    assert s.ugly_min_volume_7d_avg_usd == 750_000.0


def test_load_strategy_settings_empty_db_returns_defaults() -> None:
    client = _client([])
    s = load_strategy_settings(client)
    assert s == default_settings()


def test_load_strategy_settings_overrides_specific_value() -> None:
    rows = [{"setting_key": "clean.min_score", "setting_value": "75"}]
    client = _client(rows)
    s = load_strategy_settings(client)
    assert s.clean_min_score == 75.0
    assert s.ugly_min_score == 62.0  # unchanged default


# ── to_hard_filter_config ─────────────────────────────────────────────────────


def test_to_hard_filter_config_uses_ugly_volume_24h_floor() -> None:
    s = default_settings()
    hfc = s.to_hard_filter_config()
    assert hfc.min_volume_24h_usd == s.ugly_min_volume_24h_usd


def test_to_hard_filter_config_uses_clean_min_atr() -> None:
    s = default_settings()
    hfc = s.to_hard_filter_config()
    assert hfc.min_atr_pct == s.clean_min_atr_pct


def test_to_hard_filter_config_uses_ugly_max_atr() -> None:
    s = default_settings()
    hfc = s.to_hard_filter_config()
    assert hfc.max_atr_pct == s.ugly_max_atr_pct


# ── to_scoring_config ─────────────────────────────────────────────────────────


def test_to_scoring_config_clean_min_score() -> None:
    s = default_settings()
    sc = s.to_scoring_config()
    assert sc.clean_min_score == 70.0


def test_to_scoring_config_prob_map_matches_default() -> None:
    s = default_settings()
    sc = s.to_scoring_config()
    assert sc.prob_map == _DEFAULT_PROB_MAP


def test_to_scoring_config_custom_prob_map_propagated() -> None:
    custom_map = ((90.0, 95.0), (75.0, 80.0))
    s = StrategySettings(prob_map=custom_map)
    sc = s.to_scoring_config()
    assert sc.prob_map == custom_map


# ── to_selector_config ────────────────────────────────────────────────────────


def test_to_selector_config_max_clean_candidates() -> None:
    s = default_settings()
    selc = s.to_selector_config()
    assert selc.max_clean_candidates == 10


def test_to_selector_config_ugly_stop_pct_converted_to_fraction() -> None:
    s = default_settings()
    selc = s.to_selector_config()
    assert selc.ugly_min_stop_pct == pytest.approx(0.08)
    assert selc.ugly_max_stop_pct == pytest.approx(0.15)


def test_to_selector_config_custom_max_candidates() -> None:
    s = StrategySettings(scanner_max_clean_candidates=5, scanner_max_ugly_candidates=3)
    selc = s.to_selector_config()
    assert selc.max_clean_candidates == 5
    assert selc.max_ugly_candidates == 3


# ── primitive helpers ─────────────────────────────────────────────────────────


def test_f_returns_default_on_missing_key() -> None:
    assert _f({}, "missing.key", 99.0) == 99.0


def test_i_converts_float_string() -> None:
    assert _i({"x": "8.0"}, "x", 0) == 8


def test_b_parses_true_case_insensitive() -> None:
    assert _b({"flag": "True"}, "flag", False) is True
    assert _b({"flag": "FALSE"}, "flag", True) is False
