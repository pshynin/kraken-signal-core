# Data Model

Catalogue of Supabase tables, their Python and TypeScript mirrors, and the constraints you must respect when changing any of them.

## Source-of-Truth Hierarchy

If these three disagree, the priority is:

1. **`supabase/migrations/*.sql`** — the schema source of truth. DB constraints, defaults, and uniques are enforced there.
2. **`apps/scanner/scanner/models.py`** — Python dataclasses passed between scanner stages and written to the DB.
3. **`packages/shared-types/src/`** — TypeScript types consumed by `apps/web`. `database.ts` mirrors row shapes; `scanner.ts` mirrors `models.py`.

The Python and TypeScript types are mirrored manually, not generated automatically. Keep them aligned explicitly in the same PR.

When a column or field changes, update every affected layer in the same PR.

## Tables (in migration order)

| # | Table | Purpose | Migration |
|---|---|---|---|
| 0001 | (utilities) | `trigger_set_updated_at()` and shared helpers | 20260509000001 |
| 0002 | `assets` | The Kraken USD-spot universe; one row per tradable asset | 20260509000002 |
| 0003 | `scan_runs` | One row per scanner run, with status and aggregate counts | 20260509000003 |
| 0004 | `market_snapshots` | Per-asset, per-run market metrics (price, volume, returns) | 20260509000004 |
| 0005 | `indicator_snapshots` | Per-asset, per-timeframe indicator values (EMA/VWAP/RSI/ATR) | 20260509000005 |
| 0006 | `candidate_scores` | Per-asset score breakdown (9 factors + total + category) | 20260509000006 |
| 0007 | `candidate_recommendations` | Per-candidate trade parameters (entry/exit/stop/size) | 20260509000007 |
| 0008 | `alerts_sent` | Discord delivery log (one row per attempted send) | 20260509000008 |
| 0009 | `asset_state_history` | Immutable audit trail of asset lifecycle transitions | 20260509000009 |
| 0010 | `strategy_settings` | Key-value runtime configuration | 20260509000010 |
| 0011 | `webhook_destinations` | Webhook routing metadata (no URLs) | 20260509000011 |
| 0012 | (seed) | Seeds `strategy_settings` with default thresholds | 20260509000012 |
| 0014 | (grants) | RLS / permission grants | 20260509000014 |
| 0015 | `scan_runs` extension | Adds `timed_out` status + `run_timeout_minutes` finalisation | 20260512000015 |
| 0016 | `candidate_recommendations` fix | Entry validity columns + check fix | 20260512000016 |
| 0017 | `candidate_recommendations` extension | Entry engine columns (`setup_type`, `support_anchor_*`, etc.) | 20260512000017 |

> RLS is currently **disabled** for the single-user MVP. Enable + add policies before multi-user.

## Field Mapping by Table

Each row below shows the Supabase column, the Python field on `models.py`, and the TS type in `packages/shared-types`. Trimmed to fields that cross the layer boundary.

### `assets`

| Column | Python (`models.py`) | TS (`database.ts`) | Notes |
|---|---|---|---|
| `id` (UUID PK) | — | `Asset.id` | Resolved server-side via `asset_id_map` |
| `symbol` (TEXT, UNIQUE) | `AssetItem.symbol` | `Asset.symbol` | e.g. `"BTC"` |
| `kraken_pair` (TEXT, UNIQUE) | `AssetItem.kraken_pair` | `Asset.kraken_pair` | e.g. `"XXBTZUSD"` |
| `base_currency` / `quote_currency` | — | — | Quote currency is currently USD for the tracked Kraken USD-spot universe. |
| `is_active` (BOOL) | — | `Asset.is_active` | False = delisted by Kraken |
| `excluded_reason` (TEXT NULL) | — | `Asset.excluded_reason` | Non-null = permanently skipped |

### `scan_runs`

Status values: `'running' | 'completed' | 'partial' | 'failed' | 'timed_out'` (added in migration 0015).

### `candidate_scores`

| Column | Python | Range |
|---|---|---|
| `score_total` | `ScoreBreakdown.score_total` | 0–100 |
| `score_liquidity` | `.score_liquidity` | /20 |
| `score_upside` | `.score_upside` | /15 |
| `score_structure` | `.score_structure` | /15 |
| `score_volatility` | `.score_volatility` | /10 |
| `score_rel_strength` | `.score_rel_strength` | /10 |
| `score_volume` | `.score_volume` | /10 |
| `score_catalyst` | `.score_catalyst` | /10 |
| `score_supply_risk` | `.score_supply_risk` | /5 |
| `score_execution` | `.score_execution` | /5 |
| `category` | `.category` | `'clean' \| 'ugly' \| 'watchlist' \| 'excluded' \| NULL` |
| `probability_pct` | `.probability_pct` | Heuristic; see [scoring-model.md](scoring-model.md) |

### `candidate_recommendations`

| Column | Python (`TradeParameters`) | Constraint |
|---|---|---|
| `entry_price` | `entry_price` | — |
| `entry_price_low` / `entry_price_high` | same | `entry_price_low <= entry_price_high` (when both set) |
| `exit_price` | `exit_price` | `exit_price > entry_price` |
| `stop_loss` | `stop_loss` | `stop_loss < entry_price` |
| `suggested_size_bucket` | `suggested_size_bucket` | `crecs_size_bucket_check`: one of `SIZE_BUCKETS` |
| `expected_gain_pct` | `expected_gain_pct` | `NUMERIC(8,4)`; percent (10.0 = +10%) |
| `reward_risk_ratio` | `reward_risk_ratio` | Pure ratio |
| `setup_type` | `setup_type` | `'pullback' \| 'breakout_trigger' \| 'reclaim'` (migration 0017) |
| `preferred_entry` / `max_entry` | same | See [entry-engine.md](entry-engine.md) |
| `support_anchor_type` | `support_anchor_type` | Stored as the entry-engine anchor type string |
| `support_anchor_value` | `support_anchor_value` | NULL for `atr_fallback` |
| `state` | persisted lifecycle/status field | See [state-machine.md](state-machine.md) for semantics |

### `alerts_sent`

- `webhook_url_hash` — **SHA-256 hex digest only**. Raw URLs never persisted.
- `delivery_status` — values include `'sent'`, `'failed'`, and `'rate_limited'`
- Recent successful `alerts_sent` rows are used by the alerter dedup logic to suppress re-alerting the same `asset_id` within the configured window.

### `asset_state_history`

Insert-only. Never updated or deleted. Schema and semantics live in [state-machine.md](state-machine.md).

### `strategy_settings`

Flat key-value store. All parsing happens in `apps/scanner/scanner/settings.py`; missing keys fall back to `StrategySettings` defaults (which match the migration 0012 seed). See [scoring-model.md](scoring-model.md) and [entry-engine.md](entry-engine.md) for the keys that drive each stage.

## Critical DB Constraints

These are enforced at the database level and must not be bypassed:

- `assets.symbol` UNIQUE, `assets.kraken_pair` UNIQUE.
- `candidate_recommendations`: `stop_loss < entry_price`, `exit_price > entry_price`, `entry_price_low <= entry_price_high`.
- `crecs_size_bucket_check`: `suggested_size_bucket` must be one of `SIZE_BUCKETS` in `models.py`. **Both sides must change together.**
- `asset_state_history.asset_id` → `assets.id ON DELETE RESTRICT` (prevents accidental cascade deletes losing audit trail).
- `asset_state_history.scan_run_id` → `scan_runs.id ON DELETE SET NULL` (history survives run pruning).

## Adding a New Field — Checklist

1. Write a new migration in `supabase/migrations/` with a timestamp newer than the latest one.
2. Update the relevant Python dataclass in `apps/scanner/scanner/models.py`.
3. Mirror it in `packages/shared-types/src/database.ts` and (if it's a scanner-stage payload) `scanner.ts`.
4. If the field has a runtime threshold, add it to `strategy_settings` via a seed update and to `StrategySettings` in `settings.py` with a sensible default.
5. Update the relevant doc — usually [scoring-model.md](scoring-model.md), [entry-engine.md](entry-engine.md), or this file.
6. Run `supabase db reset` locally to confirm the migration applies cleanly from scratch.
