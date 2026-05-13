# Scoring Model

How `apps/scanner/scanner/scoring.py` turns one passing asset into a single 0–100 score and a category. The model is **deterministic**: same input → same output, every time. Do not introduce randomness.

## Overview

For every asset that clears the [hard filter](#hard-filter), the scoring engine:

1. Computes nine independent sub-scores (sum capped at 100).
2. Assigns a category — `clean`, `ugly`, or `watchlist` — using thresholds + qualification gates.
3. Maps the total to a heuristic `probability_pct` percentile.

Output is sorted by `score_total` descending. The selector then takes the top-N per category (see [entry-engine.md](entry-engine.md) for what happens after).

## Hard Filter

Before scoring runs, `filter.py` applies hard-exclusion rules. These use the **most-permissive thresholds across both clean and ugly categories** — anything that cannot qualify for either is dropped. Per-category tightening happens in the scoring engine via gates and score weighting.

| Rule | Reason key |
|---|---|
| `price_usd <= 0` | `invalid_price` |
| `volume_24h_usd < ugly.min_volume_24h_usd` | `insufficient_volume_24h` |
| `volume_7d_avg_usd < ugly.min_volume_7d_avg_usd` | `insufficient_volume_7d` |
| `rsi_14 < global.rsi_hard_min` (4h) | `rsi_below_hard_min` |
| `rsi_14 > global.rsi_hard_max` (4h) | `rsi_above_hard_max` |
| `return_3d > ugly.max_return_3d` | `extreme_pump_3d` |
| `price_vs_ema20_pct > ugly.max_price_vs_ema20_pct` (4h) | `overextended_vs_ema20` |
| `atr_pct_7d < clean.min_atr_pct` | `insufficient_volatility` |
| `atr_pct_7d > ugly.max_atr_pct` | `excessive_volatility` |
| Indicator computation failed | `no_indicator` |

Defaults match the migration 0012 seed: `min_volume_24h=$300k`, `min_volume_7d=$750k`, `rsi_hard=[48, 78]`, `max_return_3d=40%`, `max_price_vs_ema20=20%`, `atr ∈ [2.5%, 30%]`.

## The 9 Factors

Each factor returns a float clamped to its maximum. Inputs are `MarketMetrics` (4h-derived) and `AssetIndicators` (per-TF snapshots).

| # | Factor | Max | What it measures |
|---|---|---|---|
| 1 | `score_liquidity` | 20 | 24h $vol tier (8) + 7d avg $vol tier (8) + spread proxy (4) |
| 2 | `score_upside` | 15 | Distance from 7d high (6) + RSI zone (5) + 7d return (4) |
| 3 | `score_structure` | 15 | 4h trend (6) + 4h EMA alignment (5) + 4h VWAP (2) + 1h confluence (2) |
| 4 | `score_volatility` | 10 | ATR % sweet spot: 6–12% = max 10; degrades outside |
| 5 | `score_rel_strength` | 10 | `return_vs_btc_7d` tiers; falls back to absolute `return_7d` if no BTC |
| 6 | `score_volume` | 10 | `volume_ratio_20d` tiers (6) + last 4h candle vs MA20 (4) |
| 7 | `score_catalyst` | 10 | 3d return tier (5) + VWAP-reclaim setup (3) + approach to 7d high (2) |
| 8 | `score_supply_risk` | 5 | Distance from 20d high (more distance = less overhead supply) |
| 9 | `score_execution` | 5 | Price vs EMA20 proximity (3) + spread quality (2) |
| | **Total** | **100** | Capped; rounded to 2 decimals |

Each sub-scorer has graceful fallbacks for missing inputs — typically a neutral midpoint rather than zero — so partial indicator coverage degrades gradually instead of failing the whole asset.

## Category Assignment

`_assign_category()` decides the category from `score_total` + qualification gates. Order matters: clean is checked first, then ugly, then watchlist.

### `clean` — all of the following

- `score_total >= clean.min_score` (default **70**)
- `volume_24h_usd >= clean.min_volume_24h_usd` (default **$2M**)
- `volume_7d_avg_usd >= clean.min_volume_7d_avg_usd` (default **$5M**)
- `rsi_14` ∈ [`clean.rsi_preferred_min`, `clean.rsi_preferred_max`] (default **[52, 68]**) — or RSI is null
- `return_3d <= clean.max_return_3d` (default **30%**) — anti-chase
- `price_vs_ema20_pct <= clean.max_price_vs_ema20_pct` (default **12%**) — anti-chase

### `ugly` — all of the following

- `score_total >= ugly.min_score` (default **62**)
- `rsi_14` ∈ [`ugly.rsi_preferred_min`, `ugly.rsi_preferred_max`] (default **[50, 72]**) — or RSI is null

### `watchlist`

- `score_total >= watchlist.min_score` (default **55**) — and didn't qualify for clean or ugly.
- Assets below 55 still fall through to `watchlist` today because `_assign_category()` defaults to that category. If you tighten this later, expect persister and state machine changes.

### `excluded`

Not assigned by the scorer. The persister uses `category='excluded'` for hard-filtered assets when writing `candidate_scores` rows.

## Probability Map

Heuristic percentile from `score_total`. Tiers (high → low):

| score_total ≥ | probability_pct |
|---|---|
| 85 | 90 |
| 78 | 84 |
| 70 | 77 |
| 62 | 69 |
| else | `NULL` |

Loaded from `scoring.probability_map` in `strategy_settings`; defaults match migration 0012. This is a display-oriented confidence proxy, not a statistical guarantee.

## Where Each Threshold Lives

All thresholds are runtime-configurable via the `strategy_settings` table and loaded by `apps/scanner/scanner/settings.py`. The `to_*_config()` converters produce the per-stage configs:

| Stage | Config | Loaded from |
|---|---|---|
| 4 (filter) | `HardFilterConfig` | `StrategySettings.to_hard_filter_config()` |
| 5 (scoring) | `ScoringConfig` | `StrategySettings.to_scoring_config()` |
| 6 (selector) | `SelectorConfig` | `StrategySettings.to_selector_config()` |

Python defaults on each frozen dataclass match the migration 0012 seed — the scanner runs safely against an empty `strategy_settings` table.

## When to Change This

- **Adjusting weights** — edit the constants in `scoring.py` (`_MAX_*`) and update the factor table above. Sub-scorer bodies tier from the maximum; revisit the tier breakpoints when you change the max.
- **Tightening qualification gates** — edit `_assign_category()` and update the corresponding defaults in `StrategySettings`. Bump the migration 0012 seed only if you want existing prod DBs to pick up the new defaults; otherwise current rows keep their existing values.
- **Adding a 10th factor** — bump `score_total`'s sum cap of 100 (or rescale), add the column to `candidate_scores` via a new migration, mirror in `models.py` and `packages/shared-types`, and update [data-model.md](data-model.md).
- **Changing the probability map** — overwrite `scoring.probability_map` in `strategy_settings` (JSON `{score_floor: pct}`); the loader sorts descending automatically.

Keep determinism: no `random`, no `time.time()`-derived inputs, no externally-mutating state inside `score_asset`.
