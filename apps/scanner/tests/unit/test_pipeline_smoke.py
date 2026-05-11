"""Offline pipeline smoke test — stages 3-6.

Synthetic OHLCV data drives the full indicator → filter → scoring → selector
chain without any network calls or DB access. Verifies:
  - No stage crashes on realistic data
  - Output types and counts are internally consistent
  - At least one asset passes through to scoring
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from scanner.filter import run_hard_filter
from scanner.indicators import run_indicator_engine
from scanner.models import AssetOHLCV, OHLCVCandle
from scanner.scoring import run_scoring_engine
from scanner.selector import run_candidate_selector
from scanner.settings import default_settings

# ── Synthetic data helpers ────────────────────────────────────────────────────

_4H_MS = 4 * 3_600 * 1_000
_1H_MS = 3_600 * 1_000
_30M_MS = 30 * 60 * 1_000
_BASE_TS = 1_700_000_000_000


def _candles(
    n: int,
    interval_ms: int,
    start_price: float = 100.0,
    drift: float = 0.002,
    volume_usd: float = 5_000_000.0,
) -> list[OHLCVCandle]:
    """Generate n synthetic OHLCV candles targeting RSI ~58-68 and ATR ~3-5%.

    drift  — per-candle baseline % gain; oscillation provides both up/down candles.
    High-low spread is 3% of price to ensure ATR passes the 2.5% hard floor.
    """
    candles = []
    price = start_price
    for i in range(n):
        # Net pct: positive drift + slow oscillation → RSI ~60
        pct = drift + 0.005 * math.sin(i * 0.6)
        nxt = price * (1 + pct)
        # Wide H-L spread ensures ATR ≥ 3%
        high = max(price, nxt) * (1 + 0.015 + 0.005 * abs(math.sin(i * 0.7)))
        low = min(price, nxt) * (1 - 0.015 - 0.005 * abs(math.cos(i * 0.7)))
        vol = volume_usd / max(nxt, 1e-9)
        candles.append(
            OHLCVCandle(
                timestamp=_BASE_TS + i * interval_ms,
                open=round(price, 6),
                high=round(high, 6),
                low=round(low, 6),
                close=round(nxt, 6),
                volume=round(vol, 4),
            )
        )
        price = nxt
    return candles


def _bundle(
    symbol: str,
    start_price: float = 100.0,
    drift: float = 1.002,
    volume_usd: float = 8_000_000.0,
) -> AssetOHLCV:
    """Build a realistic 3-timeframe OHLCV bundle for one asset."""
    return AssetOHLCV(
        symbol=symbol,
        kraken_pair=f"X{symbol}ZUSD",
        candles_4h=_candles(250, _4H_MS, start_price, drift, volume_usd),
        candles_1h=_candles(500, _1H_MS, start_price, drift, volume_usd / 4),
        candles_30m=_candles(750, _30M_MS, start_price, drift, volume_usd / 8),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Assets: one clean-ish, one ugly-ish, one volatile junk ───────────────────

_BUNDLES = [
    _bundle("BTC", start_price=50_000.0, drift=0.002, volume_usd=200_000_000.0),
    _bundle("SOL", start_price=150.0, drift=0.002, volume_usd=20_000_000.0),
    _bundle("ALT", start_price=0.50, drift=0.002, volume_usd=900_000.0),
    _bundle("TINY", start_price=0.01, drift=0.002, volume_usd=30_000.0),  # 6*30k=$180k/day < $300k floor
]

# ── Tests ─────────────────────────────────────────────────────────────────────


def test_indicator_engine_runs_without_error() -> None:
    result = run_indicator_engine(_BUNDLES)
    assert result.success_count > 0
    assert result.total_count == len(_BUNDLES)
    for ind in result.successful:
        assert ind.symbol in {b.symbol for b in _BUNDLES}
        snap_4h = ind.snapshot_for("4h")
        assert snap_4h.rsi_14 is not None
        assert snap_4h.ema_20 is not None


def test_hard_filter_excludes_low_volume() -> None:
    ind_result = run_indicator_engine(_BUNDLES)
    filter_result = run_hard_filter(
        _BUNDLES, ind_result.successful, config=default_settings().to_hard_filter_config()
    )
    symbols_excluded = {e.symbol for e in filter_result.exclusions}

    assert "TINY" in symbols_excluded, "TINY should be excluded (vol $150k < $300k floor)"
    assert filter_result.passed_count + filter_result.excluded_count == len(_BUNDLES)
    assert filter_result.passed_count >= 1, "At least one high-volume asset should pass"


def test_scoring_engine_produces_scores() -> None:
    ind_result = run_indicator_engine(_BUNDLES)
    filter_result = run_hard_filter(
        _BUNDLES, ind_result.successful, config=default_settings().to_hard_filter_config()
    )
    scoring_result = run_scoring_engine(filter_result, config=default_settings().to_scoring_config())

    assert len(scoring_result.scores) == filter_result.passed_count
    for scored in scoring_result.scores:
        assert 0.0 <= scored.score_total <= 100.0
        assert scored.category in {"clean", "ugly", "excluded", "watchlist"}


def test_candidate_selector_output_is_consistent() -> None:
    ind_result = run_indicator_engine(_BUNDLES)
    filter_result = run_hard_filter(
        _BUNDLES, ind_result.successful, config=default_settings().to_hard_filter_config()
    )
    scoring_result = run_scoring_engine(filter_result, config=default_settings().to_scoring_config())
    selection_result = run_candidate_selector(
        scoring_result, filter_result, config=default_settings().to_selector_config()
    )

    assert selection_result.total_count == len(selection_result.all_candidates)
    for c in selection_result.clean:
        assert c.category == "clean"
        assert c.rank >= 1
        assert c.entry_price > 0
        assert c.exit_price > c.entry_price
        assert c.stop_loss < c.entry_price
    for c in selection_result.ugly:
        assert c.category == "ugly"
        assert c.rank >= 1


def test_full_pipeline_returns_no_exception() -> None:
    """End-to-end stages 3-6 on synthetic data — must not raise."""
    ind_result = run_indicator_engine(_BUNDLES)
    filter_result = run_hard_filter(
        _BUNDLES, ind_result.successful, config=default_settings().to_hard_filter_config()
    )
    scoring_result = run_scoring_engine(filter_result, config=default_settings().to_scoring_config())
    selection_result = run_candidate_selector(
        scoring_result, filter_result, config=default_settings().to_selector_config()
    )

    assert selection_result.total_count >= 0
    assert filter_result.passed_count >= 1
