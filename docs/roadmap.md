# Roadmap

What exists today, what's planned, and what we know is rough. Source of truth for "is X shipped yet?" lives in the code; this doc is the editorial summary. The README's "Implementation Status" PR table is the historical ledger and remains canonical for PR-by-PR completion.

## What Exists Today

The scanner pipeline runs end-to-end on a 6-hour cron via GitHub Actions, writes to Supabase, and pushes Discord alerts. The dashboard is live with five routes. The full numbered PR list (PRs 1–19, 21) is in [README.md](../README.md#implementation-status); below is the grouped, current-state view.

### Scanner

- Universe loader → fetcher (4h/1h/30m OHLCV via ccxt) → indicator engine → hard filter → metrics → 9-factor scoring → selector + entry engine → persister → Discord alerter.
- Deterministic scoring with a 9-factor, 0–100 model. See [scoring-model.md](scoring-model.md).
- Setup-aware entry engine: `pullback`, `breakout_trigger`, `reclaim`. See [entry-engine.md](entry-engine.md).
- Setup-aware validity gates in `selector.py` reject over-chased breakouts and infeasible pullback/reclaim entries.
- ATR-based stop sizing clamped per category; 5% exit floor; reward-risk floor enforced.
- Runtime-configurable thresholds via `strategy_settings`, with safe Python defaults that mirror migration 0012 seed values.
- Scan-run lifecycle with `running` → `completed` / `partial` / `failed` / `timed_out` (added in migration 0015).
- Immutable per-asset audit trail in `asset_state_history`. See [state-machine.md](state-machine.md).
- Discord delivery log in `alerts_sent` with SHA-256-hashed webhook URLs and an 8-hour dedup window.
- System-alert webhook for unhandled exceptions and stale-run notices.
- Docker portability via `apps/scanner/Dockerfile` + `Makefile`.

### Dashboard

- Next.js 15 (App Router, React 19) on Vercel.
- Passcode-gated middleware; HMAC-signed cookie session.
- Server-component reads from Supabase via `lib/queries/*.ts`.
- Routes: `/` overview, `/candidates`, `/scans`, `/alerts`, `/settings`.
- Shared sidebar layout via the `(app)` route group.
- Settings form writes through a Next.js Server Action.

### Database / Schema

- 16 migrations applied (timestamps `2026-05-09…` through `2026-05-12…`).
- Core schema objects created across 16 migrations, including tables such as `assets`, `scan_runs`, `market_snapshots`, `indicator_snapshots`, `candidate_scores`, `candidate_recommendations`, `alerts_sent`, `asset_state_history`, `strategy_settings`, and `webhook_destinations`, plus shared DB utilities from migration 0001.
- Critical DB constraints (uniques + CHECKs) catalogued in [data-model.md](data-model.md#critical-db-constraints).

### CI / Ops

- `.github/workflows/ci.yml` for PR checks (lint + type-check + build + test).
- `.github/workflows/scanner.yml` cron `0 */6 * * *` with `concurrency: cancel-in-progress: false` and `workflow_dispatch` manual + dry-run trigger.
- Stale-run timeout guard at start of each new run.
- `scan_summary.json` rendered as a GitHub Actions step summary.

## Planned

Tracking corresponds to README PRs not yet marked done. Where the work is small or scoped, the description below states it directly; where it isn't, this doc says so.

| PR | Scope | Status |
|---|---|---|
| 20 | Unique-symbol candidate model + correct counts | Pending |
| 22 | Discord compact table alert redesign | Pending |
| 23 | Size bucket redesign (8 tiers) | Pending |
| 24 | Denylist / policy exclusion layer | Pending |
| 25 | Diagnostics + introspection improvements | Pending |

When a PR ships, move it from this table to the "What Exists Today" section above, mark it ✅ in the README table, and add a line to [CHANGELOG.md](../CHANGELOG.md).

## Known Gaps

Real issues in the current code that aren't ambiguities or "future work". Address them when adjacent code is touched, or open a focused PR.

- **Type contracts mirrored by hand.** `apps/scanner/scanner/models.py`, `packages/shared-types/src/scanner.ts`, and `packages/shared-types/src/database.ts` must be kept in sync manually. No codegen; PRs that change one but not the others have shipped before. See [data-model.md](data-model.md).
- **No DB-level CHECK on `asset_state_history.to_state`.** Any string is accepted. The set of allowed values is enforced only by convention and by [state-machine.md](state-machine.md). Acceptable today; revisit if multi-author churn introduces inconsistent values.
- **RLS disabled.** `assets` (and likely other tables) ship with RLS off for the single-user MVP. Enable + add policies before multi-user.
- **`watchlist_min_score` is partly informational.** `_assign_category()` returns `watchlist` both for scores ≥ 55 and as the catch-all default for anything below — so the floor doesn't actually prune. See [scoring-model.md](scoring-model.md#watchlist).
- **No retry on Discord webhook failures.** A 5xx response is logged to `alerts_sent` with `delivery_status != 'sent'` and the candidate does not get a state-history `alerted` row. Dedup logic correctly considers only `'sent'` rows, so the next run will re-attempt — but there is no within-run retry.
- **`scan_summary.json` write is best-effort.** Failures are swallowed; only the workflow's `if: always()` step recovers a degraded summary.

## Out of Scope (and Likely to Stay That Way)

Set expectations for what this repo intentionally does not do.

- **Auto-trading.** The system produces ranked candidates with entry/exit/stop/size recommendations for **manual** execution. It does not place, cancel, or manage orders. Do not add order-placement endpoints without a separate design discussion.
- **Multi-exchange support.** Kraken USD-spot only. Adding another exchange would require rethinking the universe loader, the `kraken_pair` identifier, and a lot of currently-implicit assumptions.
- **Real-time / streaming data.** The pipeline is batch on a 6-hour cron. No websockets, no per-tick scoring.
- **Multi-user accounts.** Single-passcode dashboard + service-role DB access. RLS would need to be enabled and a real auth provider added before this changes.
- **Holding beyond Day 10.** The trading framework is a fixed 10-day cycle; the scanner's parameter assumptions (stop sizing, exit targets) are tuned for it. Lengthening the horizon means re-tuning, not just changing copy.
