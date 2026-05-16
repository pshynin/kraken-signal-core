# Architecture

End-to-end view of how the scanner produces candidates, how the dashboard surfaces them, and what holds the two together.

## Two Services, One Database

```text
                                    ┌──────────────────────────┐
                ┌──────────────────▶│  Discord webhooks        │
                │                   │  (clean/ugly/system)     │
                │                   └──────────────────────────┘
┌─────────────────────────┐         ┌──────────────────────────┐
│ apps/scanner (Python)   │ writes  │  Supabase Postgres       │
│ GitHub Actions cron     │────────▶│  (11 tables, migrations) │
│ every 6 hours           │         │                          │
└─────────────────────────┘         │                          │
                                    │                          │
┌─────────────────────────┐ reads   │                          │
│ apps/web (Next.js 15)   │◀────────│                          │
│ Vercel, always-on       │         └──────────────────────────┘
└─────────────────────────┘
                 
```

There is **no direct scanner ↔ web communication**. Supabase is the only shared state. The scanner writes; the dashboard reads. Discord is fire-and-forget output from the scanner only.

## The Contract Between Scanner and Web

Three things keep the two sides in sync:

1. **The Supabase schema** (`supabase/migrations/*.sql`) — the authoritative shape of the data.
2. **`packages/shared-types`** — TypeScript types consumed by `apps/web` via the pnpm workspace alias `@kraken-signal/shared-types`. `src/database.ts` mirrors Supabase row types; `src/scanner.ts` mirrors `apps/scanner/scanner/models.py`.
3. **`apps/scanner/scanner/models.py`** — Python dataclasses that the scanner pipeline passes between stages and ultimately writes to the DB.

When you change a column or model field, update every affected layer: the Supabase schema, the Python scanner models, and the shared TypeScript types. See [data-model.md](data-model.md) for the catalogue.

## Scanner Pipeline — 8 Stages

`apps/scanner/scanner/main.py` orchestrates the pipeline. Each stage produces a typed result object consumed by the next.

| # | Stage | Module | Input → Output |
|---|---|---|---|
| 1 | Universe | `universe.py` | Kraken AssetPairs API → `list[AssetItem]` |
| 2 | Fetcher | `fetcher.py` | universe → `FetchResult` (4h + 1h + 30m OHLCV) |
| 3 | Indicators | `indicators.py` | OHLCV → `IndicatorResult` (EMA, VWAP, RSI, ATR per TF) |
| 4 | Filter | `filter.py` + `metrics.py` | indicators+OHLCV → `FilterResult` (passed/excluded) |
| 5 | Scoring | `scoring.py` | `FilterResult` → `ScoringResult` (0–100, category) |
| 6 | Selector | `selector.py` + `entry_engine.py` | `ScoringResult` → `SelectionResult` (trade params) |
| 7 | Persister | `persister.py` + `state_machine.py` | `SelectionResult` → Supabase writes + asset state history rows |
| 8 | Alerter | `alerter.py` | `SelectionResult` → Discord webhook POSTs |

Three timeframes are used throughout: `4h` (structure/trend), `1h` (momentum), `30m` (entry timing). Standard accessors: `AssetIndicators.snapshot_for(tf)` and `AssetOHLCV.candles_for(tf)`.

See [entry-engine.md](entry-engine.md) for setup classification and validity-gate details.

### Dry-run gating

`_do_db = not dry_run and cfg.scanner_env != "test" and bool(cfg.supabase_url)`. When false, stages 7–8 are skipped; the pipeline still runs in-memory so `--dry-run` exercises 1–6 end to end.

### Error handling philosophy

- A stage that returns zero results aborts the run (logs error, exits 1).
- Per-asset exceptions inside a stage are logged and the asset is dropped; the run continues.
- An unhandled exception in `main` fires a Discord system alert (best-effort, never raises) and exits 2.

## Configuration Flow

All runtime thresholds live in the `strategy_settings` Supabase table (key-value: `setting_key TEXT`, `setting_value TEXT`).

```text
strategy_settings (DB)
        │
        ▼
settings.py :: load_strategy_settings(client)
        │
        ▼
StrategySettings (frozen dataclass; defaults match migration 0012 seed)
        │
        ├── .to_hard_filter_config()  ──▶  HardFilterConfig   (Stage 4)
        ├── .to_scoring_config()      ──▶  ScoringConfig      (Stage 5)
        └── .to_selector_config()     ──▶  SelectorConfig     (Stage 6)
```

If the DB is unreachable or `--dry-run` is set, `default_settings()` returns the same dataclass with seed defaults. The scanner can still run with a complete config object.

## Dashboard — `apps/web`

Next.js 15 App Router. All pages are **server components** that query Supabase directly through `lib/supabase/server.ts` (service-role key, server-only). Data flow:

```text
page.tsx  ──▶  lib/queries/*.ts  ──▶  createServerClient()  ──▶  Supabase
```

The only client-side data fetching is the settings form (`components/settings/settings-form.tsx`), which writes via a Next.js Server Action (`app/(app)/settings/actions.ts`).

**Auth:** passcode gate via `middleware.ts` + `lib/auth.ts` (HMAC-signed cookie, no JWT). Set `DASHBOARD_PASSCODE` to enable; leave unset for open-access dev mode.

**Layout:** the `(app)` route group wraps all authenticated pages with a shared sidebar (`components/shell/sidebar.tsx`). Top-level dashboard routes: `/`, `/candidates`, `/scans`, `/alerts`, `/settings`. Deep-link routes accessed via clicks: `/scans/[id]` (run detail + diagnostic panels) and `/assets/[symbol]` (per-asset state-transition history).

**Diagnostics surfaces (PR 25):** `/scans/[id]` includes panels for hard-filter exclusion counts (grouped by reason), entry-engine rejections (per-symbol with setup + reason), and below-threshold totals (watchlist + low_score). `/assets/[symbol]` reads `asset_state_history` directly to render a per-asset timeline. Symbol cells across `/candidates`, `/scans/[id]`, and `/alerts` link to the asset history page. All diagnostics queries are read-only over existing tables; no new scanner writes.

## Scheduling and Concurrency

`.github/workflows/scanner.yml`:
- Cron `0 */6 * * *` — every 6 hours at :00 UTC.
- `concurrency: { group: scanner, cancel-in-progress: false }` — queue, never cancel a running scan. This protects DB consistency: a partial write from a cancelled run could leave stale `running` rows.
- A separate guard, `timeout_stale_scan_runs()`, marks `running` rows as `timed_out` after `scanner.run_timeout_minutes` (default 120) at the start of each new run.
- `workflow_dispatch` allows manual runs with optional `--dry-run` and environment selection.

## Observability

- **`scan_summary.json`** — written at end of every run; rendered as a GitHub Actions step summary.
- **`scan_runs` table** — one row per run with status (`running` / `completed` / `partial` / `failed` / `timed_out`), counts, and error message. The `candidates_clean` and `candidates_ugly` counts are derived from rows actually persisted to `candidate_recommendations` (via `PersistResult`), so they cannot drift from what the DB holds — see [data-model.md](data-model.md#candidate-counts--canonical-definition).
- **`asset_state_history`** — immutable per-asset audit trail. See [state-machine.md](state-machine.md).
- **`ohlcv_candles`** — raw candles for hard-filter-passed assets, deduplicated append (not run-scoped). Persisted so validation tooling can detect fills / stop / target / MAE-MFE at native timeframe granularity instead of the ~6h close approximation from `market_snapshots`. See [data-model.md](data-model.md#ohlcv_candles).
- **`alerts_sent`** — every Discord delivery attempt with `delivery_status`, hashed webhook, and response metadata.
- **`DISCORD_WEBHOOK_SYSTEM`** — optional channel for unhandled-exception alerts.

## What Lives Where and Why

| Concern | Lives in | Why |
|---|---|---|
| Market data fetching | `apps/scanner/` only | Single source of truth for OHLCV; the web app never calls Kraken or ccxt. |
| Scoring logic | `apps/scanner/scanner/scoring.py` | Determinism is a critical rule; one implementation only. |
| DB schema | `supabase/migrations/` | Versioned and replayable with `supabase db reset`. |
| Type contracts | `packages/shared-types/` + `scanner/models.py` | TS for web, Python dataclasses for scanner; mirrored, not generated. |
| Thresholds | `strategy_settings` table | Editable at runtime without a deploy; seeded by migration 0012. |
| Webhook URLs | Env vars only (`DISCORD_WEBHOOK_*`) | Secrets never persisted — `alerts_sent` stores only SHA-256 hashes. |
| Auth | `apps/web/middleware.ts` | Passcode gate is dashboard-only; the scanner never serves requests. |
