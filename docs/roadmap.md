# Roadmap

What exists today, what's planned, and what we know is rough. Source of truth for "is X shipped yet?" lives in the code; this doc is the editorial summary. The README's "Implementation Status" PR table is the historical ledger and remains canonical for PR-by-PR completion.

## What Exists Today

The scanner pipeline runs end-to-end every 4 hours on an **OCI Always Free VM** (systemd timer), writes to Supabase, and pushes Discord alerts. The dashboard is live with five routes. The full numbered PR list (PRs 1–19, 21) is in [README.md](../README.md#implementation-status); below is the grouped, current-state view.

### Scanner

- Universe loader → fetcher (4h/1h/30m OHLCV via ccxt) → indicator engine → hard filter → metrics → 9-factor scoring → selector + entry engine → persister → Discord alerter.
- Deterministic scoring with a 9-factor, 0–100 model. See [scoring-model.md](scoring-model.md).
- Setup-aware entry engine: `pullback`, `breakout_trigger`, `reclaim`. See [entry-engine.md](entry-engine.md).
- Setup-aware validity gates in `selector.py` reject over-chased breakouts and infeasible pullback/reclaim entries.
- ATR-based stop sizing clamped per category; 5% exit floor; reward-risk floor enforced.
- Runtime-configurable thresholds via `strategy_settings`, with safe Python defaults that mirror migration 0012 seed values.
- Scan-run lifecycle with `running` → `completed` / `partial` / `failed` / `timed_out` (added in migration 0015).
- Immutable per-asset audit trail in `asset_state_history`. See [state-machine.md](state-machine.md).
- Discord delivery log in `alerts_sent` with SHA-256-hashed webhook URLs and a 24-hour recency window driving New-vs-Updated classification.
- System-alert webhook for unhandled exceptions and stale-run notices.
- Docker packaging via `apps/scanner/Dockerfile` + `Makefile`; production runtime on the OCI VM via the root `docker-compose.yml`.

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

- **Production scheduler is the OCI Always Free VM**, not GitHub Actions. A systemd timer (`deploy/oci/momentum-scanner.timer`) fires every 4 hours; the `oneshot` service plus an `flock` guard prevent overlapping runs, and `RuntimeMaxSec=1800` kills a hung scan. Full runbook in [deploy/oci/README.md](../deploy/oci/README.md).
- **GitHub Actions is CI/CD only.** `.github/workflows/ci.yml` runs PR checks (lint + type-check + build + test). `.github/workflows/deploy-scanner.yml` SSHes into the VM on push to `main`, fetches/resets the repo, rebuilds the image, and runs a no-side-effect `--help` sanity check — it never runs the scanner and holds no Supabase service-role key.
- The Supabase service-role key lives only in the VM's `/opt/momentum-copilot/.env`.
- The old scheduled `scanner.yml` workflow has been **removed**.
- Stale-run timeout guard at start of each new run.
- `scan_summary.json` written each run; visible in `/var/log/momentum-scanner.log` and `journalctl`.

## Planned

Tracking corresponds to README PRs not yet marked done. Where the work is small or scoped, the description below states it directly; where it isn't, this doc says so.

| PR | Scope | Status |
|---|---|---|
| 24 | Denylist / policy exclusion layer | Pending |

PRs 20 (unique-symbol candidate counts), 22 (Discord alert redesign), 23 (8-tier size buckets), and 25 (diagnostics + introspection) shipped — see [CHANGELOG.md](../CHANGELOG.md).

### Ops follow-ups (OCI runtime)

Now that the scheduler runs on the OCI VM, these are the next operational improvements:

- **Health ping / dead-man's switch** — push a heartbeat (e.g. to a healthchecks.io-style monitor) at the end of each successful run so a VM that stops scanning is noticed.
- **Alert on failed scan** — surface a non-zero scanner exit from the systemd service (e.g. an `OnFailure=` unit posting to the `DISCORD_WEBHOOK_SYSTEM` channel), independent of the scanner's own in-process crash alert.
- **systemd over cron** — done: systemd timer is the primary scheduler; cron remains only as a documented fallback (`deploy/oci/crontab.example`).

When a PR ships, move it from this table to the "What Exists Today" section above, mark it ✅ in the README table, and add a line to [CHANGELOG.md](../CHANGELOG.md).

## Known Gaps

Real issues in the current code that aren't ambiguities or "future work". Address them when adjacent code is touched, or open a focused PR.

- **Type contracts mirrored by hand.** `apps/scanner/scanner/models.py`, `packages/shared-types/src/scanner.ts`, and `packages/shared-types/src/database.ts` must be kept in sync manually. No codegen; PRs that change one but not the others have shipped before. See [data-model.md](data-model.md).
- **RLS disabled.** `assets` (and likely other tables) ship with RLS off for the single-user MVP. Enable + add policies before multi-user.

## Out of Scope (and Likely to Stay That Way)

Set expectations for what this repo intentionally does not do.

- **Auto-trading.** The system produces ranked candidates with entry/exit/stop/size recommendations for **manual** execution. It does not place, cancel, or manage orders. Do not add order-placement endpoints without a separate design discussion.
- **Multi-exchange support.** Kraken USD-spot only. Adding another exchange would require rethinking the universe loader, the `kraken_pair` identifier, and a lot of currently-implicit assumptions.
- **Real-time / streaming data.** The pipeline is batch on a 4-hour cron. No websockets, no per-tick scoring.
- **Multi-user accounts.** Single-passcode dashboard + service-role DB access. RLS would need to be enabled and a real auth provider added before this changes.
- **Holding beyond Day 10.** The trading framework is a fixed 10-day cycle; the scanner's parameter assumptions (stop sizing, exit targets) are tuned for it. Lengthening the horizon means re-tuning, not just changing copy.
