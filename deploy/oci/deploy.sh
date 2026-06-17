#!/usr/bin/env bash
#
# deploy.sh — server-side deploy for the OCI Always Free VM.
#
# Run ON the VM, normally by the GitHub Actions CD workflow over SSH
# (.github/workflows/deploy-scanner.yml). Idempotent:
#
#   1. Clone the repo to APP_DIR on first run, otherwise fetch + hard-reset to
#      origin/main.
#   2. Build the scanner image on the VM.
#   3. Lightweight sanity check: `docker compose run --rm scanner --help`.
#      argparse prints help and exits 0 BEFORE scanner.main() runs — this proves
#      the image builds and the entrypoint is runnable WITHOUT executing scanner
#      logic, touching Supabase, or risking DB/Discord side effects.
#
# It deliberately does NOT run a real scan or a --dry-run scan. Scheduled real
# runs are owned by the systemd timer (momentum-scanner.timer).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/momentum-copilot}"
REPO_URL="${REPO_URL:-https://github.com/MomentumCopilot/kraken-signal-core.git}"
BRANCH="${BRANCH:-main}"

echo "▶ Deploy target: $APP_DIR (branch: $BRANCH)"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "▶ No repo at $APP_DIR — cloning $REPO_URL"
  # Parent dir is created by the VM bootstrap; clone fills APP_DIR itself.
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  echo "▶ Existing repo — fetching and hard-resetting to origin/$BRANCH"
  git -C "$APP_DIR" fetch --prune origin
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"
echo "▶ Now at commit: $(git rev-parse --short HEAD)"

echo "▶ Building scanner image"
docker compose build scanner

echo "▶ Sanity check: container entrypoint is runnable (no scanner logic)"
docker compose run --rm scanner --help

echo "✅ Deploy complete. Scheduled runs are owned by momentum-scanner.timer."
