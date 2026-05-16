# Changelog

All notable changes to this project are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely, with one section per release or notable milestone.

## How This Repo Tracks Status

Three documents share the work, with no duplicated trackers:

- **`CHANGELOG.md`** (this file) — shipped history. Curated milestones, not a raw PR dump.
- **[`docs/roadmap.md`](docs/roadmap.md)** — pending and planned work, plus known gaps in current code.
- **[`README.md`](README.md)** — high-level entry point that links out to the above.

When a PR ships, add a line under `[Unreleased]` below. When a release is cut, move those lines into a dated entry.

## Conventions

- **Dates** are `YYYY-MM-DD` in UTC.
- **Sections** within an entry use these labels, in this order: `Added`, `Changed`, `Fixed`, `Removed`, `Security`, `Known Issues`.
- **Code references** use the `path:line` form where useful, e.g. `apps/scanner/scanner/scoring.py`.

---

## [Unreleased]

### Added

- **PR I — Validation report CLI.** `python -m scanner.validation report [--since YYYY-MM-DD]` — the capstone of the validation loop (final-state requirement #3: "judge parameter changes with evidence"). Wires H2's `fetch_trade_specs` + `fetch_forward_path` + `compute_outcome` together, aggregates the outcomes, and prints a plain-text report. Output is split into **separate `EXACT` and `CLOSE_APPROX` fidelity sections** (never blended); each section leads with an overall summary line, then breakdowns by setup type, category, size bucket, and probability tier. The `CLOSE_APPROX` section carries an explicit lower-bound caveat. On-demand compute — no `trade_outcomes` table, no migration, read-only. New pure functions `aggregate_outcomes` / `format_report` / `run_report`; `TradeSpec` gains `asset_id` (needed to fetch the forward path) and `fetch_trade_specs` now selects `setup_type` + `asset_id`. 16 new tests: aggregation (rates over filled-not-total, null setup handling, prob-tier bucketing, fidelity split order), report formatting (both sections present, breakdown titles, caveat), the two DB fetchers under a mocked Supabase client, and an end-to-end `run_report` smoke. Also closes the H2 known gap (the DB layer was previously untested). 425 unit tests total (was 409).
- **PR H2 — Trade outcome computation engine.** New read-only `scanner/validation.py` answers "did past picks work?" without touching the scan pipeline. A pure deterministic core `compute_outcome(spec, forward, fidelity)` replays one persisted `candidate_recommendations` row against the asset's forward price path and returns a `TradeOutcome` (`no_fill` / `target_hit` / `stop_hit` / `expired_open`, plus realized return and fill-price-relative MAE/MFE). Locked semantics: fill = price enters `[preferred_entry, max_entry]`; 10-day horizon (unfilled → no_fill; filled-but-unresolved → expired_open marked to the last in-horizon close); same-candle stop+target ambiguity resolves stop-first (pessimistic); MAE/MFE measured from the fill price. A thin DB layer (`fetch_trade_specs`, `fetch_forward_path`) assembles inputs, preferring `ohlcv_candles` (real high/low → `EXACT` fidelity) and falling back to `market_snapshots` 6h closes (→ `CLOSE_APPROX`); whole-trade fidelity is the lowest available across the horizon so PR I can report cohorts separately. No DB writes, no migration, no behaviour change. 14 new unit tests pin the pure core with synthetic price paths. 409 unit tests total (was 395).
- **PR H1 — OHLCV persistence (validation tooling foundation).** New `ohlcv_candles` table (migration `20260516110211`) stores raw 4h/1h/30m candles for hard-filter-passed assets. **Not run-scoped** — `UNIQUE (asset_id, timeframe, candle_timestamp)` makes the persister write a deduplicated append: the scanner re-fetches ~250 candles per timeframe each run but only genuinely new candles add rows. New `persister.upsert_ohlcv_candles()`; `persist_run` gains an optional `ohlcv_bundles` arg (filtered to the passed-filter subset so the stored asset set matches `market_snapshots`); `main.py` passes `fetch_result.successful`. Mirrored in `packages/shared-types/src/database.ts` (`OhlcvCandleRow/Insert/Update` + `Database.Tables.ohlcv_candles`). Pure addition — no behaviour change to scoring / selection / alerting. Forward-looking only: improves future validation, does nothing for historical data (raw OHLCV was never previously persisted). Groundwork for PR H2 (outcome computation) + PR I (validation report). 6 new persister tests (all-timeframes write, ms→ISO timestamp conversion, dedup conflict key, missing-asset skip, empty-input, persist_run passed-symbol filtering). 395 unit tests total (was 389).
- **PR 25 — Diagnostics + introspection.** Two new dashboard surfaces give the operator answers to "why no clean candidates this run?" and "why was asset X excluded?":
  - `/scans/[id]` gains three diagnostic panels below the candidates table: **Hard-Filter Exclusions** (counts grouped by reason), **Entry-Engine Rejections** (per-symbol with setup type + reason constant), and **Below Selection Threshold** (watchlist + low_score totals). All derived from `asset_state_history` rows for the run.
  - New `/assets/[symbol]` page renders the full state-transition timeline for one asset (newest first, capped at 100 rows). Each timeline row carries the scan_run_id link, from/to states, and reason. Reads `assets` + `asset_state_history` in a two-step query keyed by symbol.
  - Symbol cells in the `/candidates` table, `/scans/[id]` candidates table, `/scans/[id]` entry-rejection panel, and `/alerts` history table all link to `/assets/[symbol]`.
  - All queries are read-only over existing tables. No new scanner writes, no migration, no new shared types.
- **PR 22 — Mobile-first stacked alert format.** Discord alerts now render each candidate as a four-line vertical block inside a Discord embed (colour sidebar: clean=green, ugly=amber). The wide code-block table approach was abandoned because it failed on phone readability; the new format optimises for scanning a candidate quickly with one hand. Header is a single line with emoji + category + count + UTC timestamp in `M/D/YY, H:MM AM/PM` form. Candidate title line: `#R SYM • Prob P% • Size BUCKET`. Field lines: `• Entry:  V (Max V)`, `• Exit:   V (Profit +X%)`, `• Stop:   V (Risk -X%)` — Profit and Risk percentages are **derived from preferred_entry / exit_price / stop_loss geometry**, not from `tp.expected_gain_pct`. Value columns are aligned at character offset 10 (after `• Label:  `). No bot/product signature inside the body.
- **PR 23 — 8-tier size buckets.** The `SIZE_BUCKETS` set expands from 5 to 8 tiers: `2k | 2k-5k | 5k-10k | 10k-20k | 20k-35k | 35k-50k | 50k-100k | 100k+`. The new upper tiers give clean candidates finer granularity above $20k (was a single `20k+` bucket). Ugly category is unchanged (still capped at `5k-10k`). Mirrored across Python `models.SIZE_BUCKETS`, SQL `crecs_size_bucket_check`, and TS `SizeBucket` / `SIZE_BUCKETS`.
- **PR 20 — Canonical candidate-count contract.** `upsert_candidate_recommendations` now returns `(clean_count, ugly_count)` derived from the rows actually built and upserted. `persist_run` returns a new `PersistResult` dataclass carrying `asset_id_map`, `candidates_clean`, and `candidates_ugly`. `main.py` uses these counts for `complete_scan_run` and `scan_summary.json` instead of `len(selection_result.clean/.ugly)`. Counts cannot drift from persisted rows.
- **PR 20 — Dashboard "No candidates produced" banner.** `apps/web/app/(app)/page.tsx` shows an inline banner when the most recent finalised run produced zero clean and zero ugly candidates, disambiguating the previous "—"-vs-"0" presentation. Only shown for runs with `status !== 'running'`.
- **PR 2 — Entry-engine rejection audit trail.** Candidates dropped by the entry-engine validity gates (over-chased breakout, pullback/reclaim max-entry above current price, missing 20-day-high data, no qualifying reclaim anchor) are now recorded to `asset_state_history` with `to_state='entry_rejected'`. Previously these were logged-and-dropped with no auditable record.
- **PR 2 — `low_score` category.** Scores below `watchlist_min_score` (default 55) get a distinct `low_score` category instead of silently falling through to `watchlist`. Distinct from `excluded`, which remains reserved for hard-filter failures. Mirrored across Python (`models.py`), SQL (`candidate_scores.category` CHECK), and TS (`Category`, `AssetState` types).
- **PR 2 — Shared rejection-reason constants** in `apps/scanner/scanner/rejection_reasons.py`. Single source of truth for both the raise site (`entry_engine.py`) and the audit writer (`state_machine.py`).
- **PR 2 — `EntryEngineError(ValueError)`** typed exception carrying a `.reason` attribute. The selector narrows its `except` to this class so genuine bugs are not silently swallowed.
- **PR 2 — `EntryRejection` dataclass** and **`SelectionResult.rejected`** field. Mirrored in TS as `EntryRejection` interface plus `ScanOutput.entry_rejected`.

### Changed

- **PR 22** — `_DISCORD_MAX_CHARS` raised from 1900 → 3500 (alerts now sit in an embed `description` field, capped at 4096 by Discord; the old 1900 was for plain `content`). Multi-message split logic preserved: splits occur between candidate blocks, never mid-block. The `now_utc` argument to the formatter changed from an ISO-8601 string to a `datetime` object so the formatter owns its own presentation.
- **PR 23** — `_assign_size_bucket()` thresholds extended: clean candidates can now reach `20k-35k` (score ≥ 80, v7 ≥ $50M), `35k-50k` (≥ 82, ≥ $75M), `50k-100k` (≥ 85, ≥ $100M), and `100k+` (≥ 88, ≥ $200M). Existing 5-tier ladder for `5k-10k`, `10k-20k`, `2k-5k` is unchanged. Ugly ladder is unchanged.
- **PR 20** — `upsert_candidate_recommendations` return type: `int` → `tuple[int, int]`. `persist_run` return type: `dict[str, str]` → `PersistResult`.
- **PR 2** — `_assign_category()` returns `'low_score'` for scores below the watchlist floor instead of returning `'watchlist'` as a catch-all default. `ScoringResult` gains a `low_score` property mirroring `watchlist`.
- **PR 2** — `state_machine._build_transition_rows()` emits rows for the new `low_score` and `entry_rejected` states. Module docstring updated.

### Schema

- **Hardening B** — Migration `20260516100203_check_asset_state_history_to_state.sql` adds `ash_to_state_check`, a CHECK pinning `asset_state_history.to_state` to the 7 values the scanner writes (`candidate_clean`, `candidate_ugly`, `watchlist`, `low_score`, `entry_rejected`, `excluded`, `alerted`). Plain `ADD CONSTRAINT` (not `NOT VALID`): Postgres validates existing rows at migration time, so a legacy out-of-set value fails the migration loudly — the intended signal for this single-DB project. **Not locally verified** (no local Supabase); run `SELECT DISTINCT to_state FROM asset_state_history;` before applying to prod.
- **PR 23** — Migration `20260514122521_extend_size_buckets_8_tiers.sql` drops `crecs_size_bucket_check`, backfills existing rows holding `'20k+'` to `'20k-35k'` (conservative — maps old "smallest above-20k" tier to new "smallest above-20k" tier), and recreates the constraint with the 8-tier value set only. Lossy for distinguishing old `20k+` rows from the new finer-grained tiers; pre-existing 5-tier `'20k+'` rows remain mapped to `'20k-35k'` after migration.
- **PR 2** — Migration `20260514011523_extend_cscores_category_check.sql` drops and recreates `cscores_category_check` to permit `'low_score'`.

### Removed

- **PR 22** — Dead `format_candidate_embed` function deleted along with the `_TABLE_HEADER` / `_TABLE_SEP` module-level constants and the old `format_table_messages` (replaced by `format_stacked_messages`). The 8 unit tests covering the embed builder and the 5 covering the table format were removed and replaced by 18 new tests for the stacked format.

### Fixed

- **Hardening B** — Closed known gap #3: `asset_state_history.to_state` is now constrained at the DB level (see Schema). Removed from `docs/roadmap.md`; `docs/state-machine.md` and `docs/data-model.md` updated to state the constraint exists.
- **Hardening C** — Closed known gap #6: `_post_to_webhook` now retries transient Discord failures (connection/timeout errors, HTTP 429, HTTP 5xx) up to 3 attempts with exponential backoff (1s, 2s). A 429 `Retry-After` header is honored when present. Permanent failures (4xx other than 429) raise immediately — no point retrying a malformed payload. The caller's failure handling is unchanged; retry just reduces how often a batch is recorded `delivery_status='failed'`.
- **Hardening D** — Closed known gap #7: `_write_summary` no longer swallows write failures silently. A failure now logs at ERROR (surfaces in the GHA run log) and fires a best-effort `DISCORD_WEBHOOK_SYSTEM` alert. Still never raises — the workflow's `if: always()` step remains the outer safety net.
- **PR 1** — `scanner_alert_dedup_hours` from `strategy_settings` now reaches `AlertConfig`. `load_alert_config()` accepts an optional `StrategySettings`; when provided, its `scanner_alert_dedup_hours` overrides the `AlertConfig` 8h default. Webhook URLs continue to come from environment variables only.
- **PR 2** — Closed known gap #5 (`watchlist_min_score` was informational only). Removed from `docs/roadmap.md` known-gaps list.

### Tests

- PR 22 adds 23 new unit tests covering: header format (clean/ugly/timestamp), stacked-block field order (Entry/Exit/Stop), no separate Size line (Size lives on the title), Prob and Size on the title, no "Gain" field anywhere, Profit % derived from `(exit − preferred_entry) / preferred_entry`, Risk % derived from `(stop − preferred_entry) / preferred_entry` (always negative), value-column alignment at offset 10, setup-abbreviation-omission, notes-and-signature absence, the `probability_pct is None` invariant (raises ValueError), empty-input handling, character-cap splitting between candidate blocks, embed payload structure (color, no title, no footer), and `run_alerter` posting `{'embeds': [...]}` rather than `{'content': ...}`. Plus one golden sample-output test pinning the full rendered body for a 2-candidate fixture matching the locked design. Removed 13 tests for the old format. Net total: 379 unit tests (was 369).
- PR 23 adds 7 net new unit tests: 4 new tier tests (`100k+`, `50k-100k`, `35k-50k`, `20k-35k`), 2 boundary tests (high-score / low-volume falls to `20k-35k`; high-volume / low-score falls to `10k-20k`), 1 ugly-category cap test, and 1 SIZE_BUCKETS-membership sweep. Removed the old `20k+` test (no longer a valid tier).
- PR 20 adds 4 unit tests (3 persister, 1 selector regression guard against clean/ugly symbol overlap).
- PR 2 added 24 unit tests across state machine, scoring boundary, selector validity gates, entry-engine typed errors, and parametrised invariant-table coverage.
- Hardening C adds 6 retry tests (4xx no-retry, 5xx retry-then-succeed, give-up-after-max, Retry-After honored, connection-error retry, connection-error exhaustion). Hardening D adds 4 `_write_summary` tests (success, failure does not raise, failure logs ERROR, failure fires system alert). New `tests/unit/test_main_observability.py`.
- Total unit tests: 389 (was 334 at baseline).

### Docs

- **Hardening B** — `docs/data-model.md` migrations table gains the 0020 row; `ash_to_state_check` added to the Critical DB Constraints list. `docs/state-machine.md` "States" intro updated to state the CHECK exists. `docs/roadmap.md` Known Gaps drops #3, #6, #7 (all closed by this PR).
- **PR 23** — `docs/entry-engine.md` Size Buckets table updated to the 8-tier ladder. `docs/data-model.md` migrations table gains the 0019 row.
- **PR 20** — `docs/data-model.md` gains a "Candidate Counts — Canonical Definition" section pinning the single source of truth. `docs/architecture.md` Observability section now links to it.

### Known Issues

- `ScanStatus` TS type in `packages/shared-types/src/enums.ts` is missing `'timed_out'` (added in migration 0015); pre-existing drift, not from these changes. Remaining open gaps: type-mirror drift (no codegen) and RLS disabled — both tracked in `docs/roadmap.md`.

---

## [2026-05-13] — Baseline documentation snapshot

First written CHANGELOG entry. Captures the state of the codebase as of this date. This is a baseline snapshot, not a release; future entries should track deltas from here.

### Added

- **Curated CHANGELOG, roadmap, and architecture docs.** Adopts the three-way split described above. `CLAUDE.md` plus `docs/{architecture,data-model,scoring-model,entry-engine,state-machine,local-dev,roadmap}.md` are introduced as the canonical reference set.

### Known Issues (at snapshot time)

Carried forward from [docs/roadmap.md](docs/roadmap.md#known-gaps). The full list lives there; the high-impact ones are:

- `scanner_alert_dedup_hours` is parsed from `strategy_settings` but not wired into `AlertConfig`; the dedup window is effectively fixed at 8h.
- Python ↔ TypeScript type contracts (`scanner/models.py` ↔ `packages/shared-types/src/`) are mirrored by hand and have drifted in past PRs.
- `asset_state_history.to_state` has no DB-level CHECK constraint; allowed values are enforced only by convention.
- RLS is disabled across the schema for the single-user MVP.

---

## Historical milestones before changelog adoption

Pre-snapshot work is summarised below in milestone buckets rather than re-litigated as 19+ dated entries. PR ranges in parentheses reference the historical PR ledger that lived in the README before this CHANGELOG was adopted; they are included for traceability, not as a tracker. Pending work is **not** listed here — see [docs/roadmap.md](docs/roadmap.md).

### Foundation (PRs 1–3)

- Repo scaffold: pnpm workspaces, scanner + web app skeletons, shared-types package.
- Versioned Supabase Postgres schema with the initial table set, applied via the Supabase CLI.
- TypeScript ↔ Python contract conventions established (`packages/shared-types` mirrors `scanner/models.py`).

### Scanner core (PRs 4–11)

- Kraken universe loader and OHLCV fetcher (4h / 1h / 30m via ccxt).
- Indicator engine (EMA 20/50/200, VWAP, RSI-14, ATR-14 via pandas-ta).
- Hard filter + market metrics, deterministic 9-factor scoring engine, candidate selector with trade parameters.
- Asset state machine writing the immutable `asset_state_history` audit trail.
- Discord alerter with SHA-256-hashed webhook persistence and an 8-hour dedup window.
- Subsequent setup-aware entry engine work introduced `pullback`, `breakout_trigger`, and `reclaim` classification plus selector-side validity gates.

### Dashboard (PRs 13–16, 19)

- Next.js 15 App Router dashboard scaffold with passcode-gated middleware (`apps/web/middleware.ts` + cookie session).
- Candidate, scan-history, alert-history, and settings pages backed by server components reading directly from Supabase.
- Shared sidebar layout via the `(app)` route group.
- Settings form writes through a Next.js Server Action.

### Scheduling, reliability & ops (PRs 12, 17, 18, 21)

- GitHub Actions cron at `0 */6 * * *` with `concurrency: cancel-in-progress: false` and a `workflow_dispatch` manual / dry-run trigger.
- Docker portability for the scanner (`apps/scanner/Dockerfile` + `Makefile`).
- End-to-end smoke tests and observability surface: `scan_summary.json` rendered as the GitHub Actions step summary, plus the optional `DISCORD_WEBHOOK_SYSTEM` channel for unhandled-exception alerts.
- Scan-run finalisation: explicit `running` → `completed` / `partial` / `failed` / `timed_out` lifecycle and the stale-run timeout guard at the start of each new run (migration 0015).

---

## Template for Future Entries

Copy this block when starting a new entry; delete sections that don't apply.

```markdown
## [YYYY-MM-DD] — Short title

### Added
- One bullet per addition.

### Changed
- One bullet per change. Note any breaking impact.

### Fixed
- One bullet per fix. Reference the issue or PR where useful.

### Removed
- One bullet per removal. Call out migration steps if needed.

### Security
- Reserve for credential/handling changes, dependency CVEs, RLS work.

### Known Issues
- Anything newly discovered or still open that users need to know.
```
