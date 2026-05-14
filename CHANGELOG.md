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

- **PR 20 — Canonical candidate-count contract.** `upsert_candidate_recommendations` now returns `(clean_count, ugly_count)` derived from the rows actually built and upserted. `persist_run` returns a new `PersistResult` dataclass carrying `asset_id_map`, `candidates_clean`, and `candidates_ugly`. `main.py` uses these counts for `complete_scan_run` and `scan_summary.json` instead of `len(selection_result.clean/.ugly)`. Counts cannot drift from persisted rows.
- **PR 20 — Dashboard "No candidates produced" banner.** `apps/web/app/(app)/page.tsx` shows an inline banner when the most recent finalised run produced zero clean and zero ugly candidates, disambiguating the previous "—"-vs-"0" presentation. Only shown for runs with `status !== 'running'`.
- **PR 2 — Entry-engine rejection audit trail.** Candidates dropped by the entry-engine validity gates (over-chased breakout, pullback/reclaim max-entry above current price, missing 20-day-high data, no qualifying reclaim anchor) are now recorded to `asset_state_history` with `to_state='entry_rejected'`. Previously these were logged-and-dropped with no auditable record.
- **PR 2 — `low_score` category.** Scores below `watchlist_min_score` (default 55) get a distinct `low_score` category instead of silently falling through to `watchlist`. Distinct from `excluded`, which remains reserved for hard-filter failures. Mirrored across Python (`models.py`), SQL (`candidate_scores.category` CHECK), and TS (`Category`, `AssetState` types).
- **PR 2 — Shared rejection-reason constants** in `apps/scanner/scanner/rejection_reasons.py`. Single source of truth for both the raise site (`entry_engine.py`) and the audit writer (`state_machine.py`).
- **PR 2 — `EntryEngineError(ValueError)`** typed exception carrying a `.reason` attribute. The selector narrows its `except` to this class so genuine bugs are not silently swallowed.
- **PR 2 — `EntryRejection` dataclass** and **`SelectionResult.rejected`** field. Mirrored in TS as `EntryRejection` interface plus `ScanOutput.entry_rejected`.

### Changed

- **PR 20** — `upsert_candidate_recommendations` return type: `int` → `tuple[int, int]`. `persist_run` return type: `dict[str, str]` → `PersistResult`.
- **PR 2** — `_assign_category()` returns `'low_score'` for scores below the watchlist floor instead of returning `'watchlist'` as a catch-all default. `ScoringResult` gains a `low_score` property mirroring `watchlist`.
- **PR 2** — `state_machine._build_transition_rows()` emits rows for the new `low_score` and `entry_rejected` states. Module docstring updated.

### Schema

- **PR 2** — Migration `20260514011523_extend_cscores_category_check.sql` drops and recreates `cscores_category_check` to permit `'low_score'`.

### Fixed

- **PR 1** — `scanner_alert_dedup_hours` from `strategy_settings` now reaches `AlertConfig`. `load_alert_config()` accepts an optional `StrategySettings`; when provided, its `scanner_alert_dedup_hours` overrides the `AlertConfig` 8h default. Webhook URLs continue to come from environment variables only.
- **PR 2** — Closed known gap #5 (`watchlist_min_score` was informational only). Removed from `docs/roadmap.md` known-gaps list.

### Tests

- PR 20 adds 4 unit tests (3 persister, 1 selector regression guard against clean/ugly symbol overlap).
- PR 2 added 24 unit tests across state machine, scoring boundary, selector validity gates, entry-engine typed errors, and parametrised invariant-table coverage.
- Total unit tests: 362 (was 334 at baseline).

### Docs

- **PR 20** — `docs/data-model.md` gains a "Candidate Counts — Canonical Definition" section pinning the single source of truth. `docs/architecture.md` Observability section now links to it.

### Known Issues

- `to_state` still has no DB-level CHECK constraint — the new `entry_rejected` and `low_score` values are enforced only by convention. A future migration will close this (carried as gap #3 in `docs/roadmap.md`).
- `ScanStatus` TS type in `packages/shared-types/src/enums.ts` is missing `'timed_out'` (added in migration 0015); pre-existing drift, not from these changes.

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
