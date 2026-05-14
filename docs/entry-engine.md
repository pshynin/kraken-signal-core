# Entry Engine

How `apps/scanner/scanner/entry_engine.py` and `selector.py` turn a scored candidate into a concrete entry/exit/stop plan. Scoring decides *whether* a coin qualifies; the entry engine decides *where* to enter and where to bail out.

## Setup Types

Every selected candidate is classified into exactly one of three setups. `classify_setup()` evaluates them in this order; the **first match wins**.

### 1. `breakout_trigger`

Trade the break of the 20-day high with momentum behind it.

Conditions (all required):
- `dist_from_20d_high >= -3%` (within 3% of the 20d high)
- `return_7d > +8%`
- 4h `trend_state` ∈ {`up`, `strong_up`}

Only setup where `preferred_entry` may sit **above** current price (limit order triggers on the break).

### 2. `reclaim`

Price has just re-crossed a key level from below and is showing positive short-term momentum.

Conditions (all required):
- 4h `price_vs_ema20_pct` ∈ [`-3%`, `+4%`]
- `return_3d > 0`
- `return_7d` ∈ [`-12%`, `+8%`] (above this range is breakout territory, not reclaim)
- 4h `trend_state` ∈ {`up`, `neutral`}

Anchor must sit between 0.1% and 4% **below** current price — the "freshly reclaimed" zone.

### 3. `pullback` (default)

Buy a retracement in an established uptrend. This is the default fallback for candidates that do not match the first two setup types.

## Entry Anchors

`compute_entry_levels()` produces `(preferred_entry, max_entry, support_anchor_type, support_anchor_value)` based on setup type.

| Setup | Anchor priority | `support_anchor_type` written to DB |
|---|---|---|
| `pullback` | EMA-20 → EMA-50 → VWAP (highest qualifying level wins); otherwise ATR fallback | `ema_20` / `ema_50` / `vwap` / `atr_fallback` |
| `breakout_trigger` | Reconstructed 20d high from `dist_from_20d_high` | `20d_high_trigger` if approaching, `above_20d_high` if already above |
| `reclaim` | EMA-20 → VWAP (highest qualifying level in the proximity window wins) | `ema_20` / `vwap` |

Anchor constants live at module scope: `ANCHOR_EMA20`, `ANCHOR_EMA50`, `ANCHOR_VWAP`, `ANCHOR_ATR`, `ANCHOR_20D_HIGH_TRIGGER`, `ANCHOR_ABOVE_20D_HIGH`. `support_anchor_value` is `NULL` for `atr_fallback` (synthetic, no real level to record).

### Anchor Qualifiers

- **Pullback** — anchor must be at least `min_pullback_discount` (default **2%**) below price. ATR fallback is `max(atr_pct × 1.0, 3%)` below market.
- **Reclaim** — anchor must be within `[0.1%, 4%]` below price (the `_RECLAIM_MIN_PROXIMITY` … `_RECLAIM_MAX_PROXIMITY` window). If no level qualifies, the candidate is dropped with a `ValueError`.

### Buffers

Small fill-headroom buffers are baked into `preferred_entry`:

- Pullback / Reclaim: anchor × `(1 + 0.25%)` — sits just above the anchor so a limit order can fill on a retest.
- Breakout (approaching): 20d_high × `(1 + 0.2%)` — triggers just above the breakout level.
- Breakout (already above): current price × `(1 - 0.1%)` — enter just below market.

## Validity Gates (in `selector.py`)

After `compute_entry_levels()` returns, the selector enforces:

| Setup | Gate |
|---|---|
| `pullback` / `reclaim` | `max_entry < current_price` — both bounds must sit entirely below market |
| `breakout_trigger` | `preferred_entry <= current_price × (1 + max_chase_current_price_pct)` — default ceiling **+3%** above market |

Candidates that fail are dropped from `SelectionResult.clean`/`.ugly` and recorded on `SelectionResult.rejected` as `EntryRejection` records. The state machine then persists each rejection to `asset_state_history` with `to_state='entry_rejected'` and `reason` set to one of the constants in `scanner.rejection_reasons`. See [state-machine.md](state-machine.md#entry-rejection-reasons) for the full list and metadata shape. **No relaxation of these gates** — they exist to prevent the scanner from suggesting chases.

Internally, both validity gates and the `entry_engine.py` raise sites use a typed `EntryEngineError(ValueError)` exception that carries the rejection-reason constant on `.reason`. The selector catches only this class — other exceptions still propagate so genuine bugs are not silently swallowed.

## Stop Loss

Computed in `_compute_stop_pct()` and applied as `stop_loss = entry_price × (1 - stop_pct)`. Always satisfies `stop_loss < entry_price` by construction.

| Category | `stop_pct` formula | Clamp |
|---|---|---|
| `clean` | `atr_pct × 1.5` (fallback 6% if ATR is null) | `[3%, 12%]` |
| `ugly` | `atr_pct × 2.0` (fallback 10% if ATR is null) | `[8%, 15%]` |

ATR multipliers and clamp bounds come from `SelectorConfig` (defaults seeded by migration 0012).

## Exit Price

Three-step computation in `compute_trade_parameters()`:

1. **R:R floor.** `rr_exit = entry + min_rr × (entry - stop)` where `min_rr` is `clean.min_reward_risk` (default **2.0**) or `ugly.min_reward_risk` (default **2.5**).
2. **Technical target.** If `dist_from_20d_high < -3%`, reconstruct the 20d high (`price / (1 + dist)`) and set `tech_exit = 20d_high × 0.97` (3% below the high — conservative).
3. **5% hard floor.** `exit_price = max(rr_exit, tech_exit, entry × 1.05)`.

Result: `exit_price > entry_price` is guaranteed by the 5% floor.

## Size Buckets

Assigned by `_assign_size_bucket()` based on `score_total` and `volume_7d_avg_usd`. The 8-tier ladder gives clean candidates finer upper-end granularity; ugly candidates remain capped at `5k-10k` (sub-$5M-liquidity assets do not warrant 5-figure-plus sizing). Returned values must match `SIZE_BUCKETS` in `models.py` and the `crecs_size_bucket_check` DB constraint.

| Category | Score | 7d avg volume | Bucket |
|---|---|---|---|
| `clean` | ≥ 88 | ≥ $200M | `100k+` |
| `clean` | ≥ 85 | ≥ $100M | `50k-100k` |
| `clean` | ≥ 82 | ≥ $75M | `35k-50k` |
| `clean` | ≥ 80 | ≥ $50M | `20k-35k` |
| `clean` | ≥ 75 | ≥ $20M | `10k-20k` |
| `clean` | ≥ 70 | ≥ $10M | `5k-10k` |
| `clean` | (else) | (else) | `2k-5k` |
| `ugly` | ≥ 70 | ≥ $5M | `5k-10k` |
| `ugly` | ≥ 65 | — | `2k-5k` |
| `ugly` | (else) | — | `2k` |

## Notes String

`_build_notes()` writes a compact human-readable rationale to `TradeParameters.notes`. Format:

```text
trend:<state> | ema:<alignment> | vwap:<state> | rsi:<n> | vol:<ratio>x | ret7d:<pct>
```

Used by both the Discord alert formatter and the dashboard candidates table.

## When to Change This

- **New setup type** — add a fourth branch in `classify_setup()` and a new `_*_entry_levels()` function. Update the `setup_type` set in `models.py` and add a CHECK constraint (or relax it) via migration. Mirror the new value in `packages/shared-types/src/enums.ts`.
- **New anchor type** — add an `ANCHOR_*` constant, update the anchor-priority list for the relevant setup, and document the new string in [data-model.md](data-model.md) under `support_anchor_type`.
- **Loosening a validity gate** — don't. These are an invariant. If you must, change the gate in `selector.py` and the corresponding test in `tests/unit/test_selector.py` — and write down why in the PR.
- **Re-tuning stops / exits / sizes** — edit `SelectorConfig` defaults in `selector.py` and the corresponding `StrategySettings` defaults. Update the migration 0012 seed if you want existing DBs to pick up the change.
