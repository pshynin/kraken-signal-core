#!/usr/bin/env bash
#
# momentum-scanner.sh — production scanner runner for the OCI Always Free VM.
#
# Runs exactly one scan via Docker Compose, guarded by flock so two runs can
# never overlap (a slow scan must finish before the next 4-hour tick starts).
#
# Invoked by:
#   - the systemd service `momentum-scanner.service` (preferred), or
#   - cron (see crontab.example, the fallback), or
#   - manually for a one-off run.
#
# It does NOT pull or build — deployment (git fetch + docker compose build) is
# handled by deploy/oci/deploy.sh via GitHub Actions. This script only *runs*
# the already-built image, so a scheduled scan is never blocked on a build.
#
# Usage:
#   deploy/oci/momentum-scanner.sh            # one real scan (writes DB, alerts)
#   deploy/oci/momentum-scanner.sh --dry-run  # no DB writes, no Discord alerts
set -euo pipefail

# ── Configuration (override via environment) ──────────────────────────────────
APP_DIR="${APP_DIR:-/opt/momentum-copilot}"
LOG_FILE="${LOG_FILE:-/var/log/momentum-scanner.log}"
LOCK_FILE="${LOCK_FILE:-/var/lock/momentum-scanner.lock}"

# ── Logging helper ────────────────────────────────────────────────────────────
log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >>"$LOG_FILE"
}

run_scan() {
  log "=== scan start (args: ${*:-<none>}) ==="
  cd "$APP_DIR"

  # `docker compose run --rm scanner` runs `python -m scanner.main` once and
  # exits (the scanner ENTRYPOINT). Extra args (e.g. --dry-run) are appended.
  if docker compose run --rm scanner "$@" >>"$LOG_FILE" 2>&1; then
    log "=== scan completed OK ==="
  else
    rc=$?
    log "=== scan FAILED (exit $rc) ==="
    return "$rc"
  fi
}

# ── flock guard: non-blocking, skip the tick if a scan is still running ────────
# fd 9 holds the lock for the lifetime of this process.
exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
  log "another scan is still running — skipping this tick"
  exit 0
fi

run_scan "$@"
