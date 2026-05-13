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

_No unreleased changes yet._

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
