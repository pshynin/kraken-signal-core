# OCI VM Scanner Runtime

The scheduled scanner runs on an **Oracle Cloud Infrastructure (OCI) Always Free
VM**, not GitHub Actions. This is the production scheduler.

- **Where it runs:** OCI Always Free VM, `/opt/momentum-copilot`, in Docker.
- **How often:** every 6 hours (00:00 / 06:00 / 12:00 / 18:00 UTC) via a systemd timer.
- **What it runs:** `docker compose run --rm scanner` → `python -m scanner.main`.
- **Where secrets live:** `/opt/momentum-copilot/.env` on the VM only. The
  Supabase service-role key is **never** stored in GitHub Actions.
- **How code is deployed:** GitHub Actions (`.github/workflows/deploy-scanner.yml`)
  SSHes in on push to `main`, fetches/resets the repo, rebuilds the image, and
  runs a no-side-effect `--help` sanity check. It never runs a real scan.
- **Overlap protection:** systemd `oneshot` (no second instance while one runs)
  plus an `flock` guard in `momentum-scanner.sh`.

GitHub Actions is **CI/CD only**. There is no scheduled scanner workflow.

---

## 1. Create the OCI Always Free VM

1. OCI Console → **Compute → Instances → Create Instance**.
2. **Shape:** `VM.Standard.A1.Flex` (Ampere A1, Always Free eligible).
   - **1 OCPU / 4 GB RAM** is plenty for v1 (2 GB also works).
3. **Image:** Canonical Ubuntu 22.04 (this guide assumes the `ubuntu` user;
   for Oracle Linux the deploy user is `opc` — adjust `User=` in
   `momentum-scanner.service` accordingly).
4. Add your **SSH public key** (you'll use the matching private key for both
   manual SSH and the GitHub Actions deploy secret).
5. Create. Note the **public IP** → this is `OCI_DEPLOY_HOST`.
6. **Networking:** the default egress rules are enough (scanner only makes
   outbound calls to Kraken, Supabase, Discord). Ensure inbound **TCP 22** is
   allowed in the VCN security list / NSG so GitHub Actions can SSH.

## 2. Install dependencies (on the VM)

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl

# Docker Engine + Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sudo sh

# Let the deploy user run docker without sudo
sudo usermod -aG docker "$USER"
newgrp docker   # or log out/in

docker --version
docker compose version
```

## 3. Clone the repo to /opt/momentum-copilot

This is a **private** repository, so git on the VM needs read access. Configure
one of these for the deploy user **before** cloning (the GitHub Actions deploy
also relies on it for `git fetch`/`reset`):

- **Read-only deploy key (recommended):** add an SSH key to the repo
  (Settings → Deploy keys, read-only), put the private half at `~/.ssh/id_ed25519`
  on the VM, and clone via SSH (`git@github.com:...`).
- **Fine-grained PAT:** a token with read-only Contents access, stored via
  `git config --global credential.helper store` (or a `~/.git-credentials` entry),
  and clone via HTTPS.

```bash
sudo mkdir -p /opt/momentum-copilot
sudo chown "$USER:$USER" /opt/momentum-copilot

# SSH (deploy key) — recommended:
git clone git@github.com:MomentumCopilot/kraken-signal-core.git /opt/momentum-copilot
# …or HTTPS (PAT credential helper configured):
# git clone https://github.com/MomentumCopilot/kraken-signal-core.git /opt/momentum-copilot

cd /opt/momentum-copilot
```

> The GitHub Actions deploy workflow will also clone automatically on its first
> run if the directory is empty — but only if the VM's git credentials are
> already configured. Cloning once here verifies access and lets you create
> `.env` and install the timer before the first deploy.

## 4. Create the VM `.env`

```bash
cp deploy/oci/.env.example /opt/momentum-copilot/.env
chmod 600 /opt/momentum-copilot/.env
nano /opt/momentum-copilot/.env
```

### Required environment variables

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | **Lives only here, never in GitHub** |
| `DISCORD_WEBHOOK_CLEAN` | optional | omit to disable that channel |
| `DISCORD_WEBHOOK_UGLY` | optional | |
| `DISCORD_WEBHOOK_SYSTEM` | optional | system / crash alerts |
| `SCANNER_ENV` | recommended | set to `production` |
| `SCANNER_TRIGGERED_BY` | optional | `schedule` |
| `SCANNER_VERSION` | optional | free-form tag, e.g. `oci` |

The root `docker-compose.yml` reads this file via `env_file: .env`.

## 5. Build the image and confirm the scanner can run manually

```bash
cd /opt/momentum-copilot
docker compose build scanner

# Sanity check — no scanner logic, no Supabase, no side effects:
docker compose run --rm scanner --help

# Dry run — exercises the real pipeline but writes NOTHING to DB / Discord.
# Requires a valid SUPABASE_URL in .env.
docker compose run --rm scanner --dry-run
```

## 6. Configure the systemd timer (primary scheduler)

```bash
sudo cp /opt/momentum-copilot/deploy/oci/momentum-scanner.service /etc/systemd/system/
sudo cp /opt/momentum-copilot/deploy/oci/momentum-scanner.timer   /etc/systemd/system/

# If your deploy user is NOT `ubuntu`, edit User= in the service unit:
#   sudo nano /etc/systemd/system/momentum-scanner.service

# Stable log file the runner tees to:
sudo touch /var/log/momentum-scanner.log
sudo chown "$USER:$USER" /var/log/momentum-scanner.log

sudo systemctl daemon-reload
sudo systemctl enable --now momentum-scanner.timer
```

Verify the schedule:

```bash
systemctl list-timers momentum-scanner.timer   # shows next fire time
systemctl status momentum-scanner.timer
```

Run one scan immediately (does not affect the schedule):

```bash
sudo systemctl start momentum-scanner.service
```

> **Cron fallback:** if you cannot use systemd, see `crontab.example`. systemd is
> the supported path; cron is documented for completeness only.

## 7. Confirm logs

```bash
# Stable file (written by momentum-scanner.sh):
tail -f /var/log/momentum-scanner.log

# systemd journal for the service:
journalctl -u momentum-scanner.service -f
journalctl -u momentum-scanner.service --since "today"
```

## 8. Configure the GitHub Actions deploy

Add these **repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `OCI_DEPLOY_HOST` | VM public IP / hostname |
| `OCI_DEPLOY_USER` | SSH user (`ubuntu`, or `opc` on Oracle Linux) |
| `OCI_DEPLOY_SSH_KEY` | private key whose public half is on the VM |
| `OCI_DEPLOY_PORT` | optional, defaults to `22` |

Push to `main` (touching `apps/scanner/**`, `docker-compose.yml`, or
`deploy/oci/**`) — or run the workflow manually via **Actions → Deploy Scanner
(OCI) → Run workflow**. It will fetch/reset, rebuild, and run `--help`. Watch the
Actions log; the final line should be `✅ Deploy complete`.

### Secrets to REMOVE from GitHub after migration

These were only used by the now-deleted `scanner.yml`. Once OCI is confirmed
working, delete them from GitHub so the service-role key is not stored there:

- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_URL`
- `DISCORD_WEBHOOK_CLEAN`
- `DISCORD_WEBHOOK_UGLY`
- `DISCORD_WEBHOOK_SYSTEM`

(`ci.yml` uses inline dummy values, so removing these does not break CI.)

---

## Validation checklist

- [ ] `docker compose build scanner` succeeds on the VM.
- [ ] `docker compose run --rm scanner --help` exits 0 (no Supabase needed).
- [ ] `docker compose run --rm scanner --dry-run` completes with no DB/Discord writes.
- [ ] `systemctl list-timers momentum-scanner.timer` shows the next 6h tick.
- [ ] `sudo systemctl start momentum-scanner.service` produces a real run; row appears in Supabase `scan_runs`.
- [ ] `journalctl -u momentum-scanner.service` and `/var/log/momentum-scanner.log` both show output.
- [ ] A push to `main` triggers **Deploy Scanner (OCI)** and it ends with `✅ Deploy complete`.
- [ ] Two manual runs started back-to-back: the second logs `another scan is still running — skipping this tick`.
- [ ] GitHub no longer has a scheduled scanner workflow; old Supabase/Discord secrets removed.

## Rollback

**Roll back code to a previous commit (on the VM):**

```bash
cd /opt/momentum-copilot
git log --oneline -n 10          # find the good commit
git reset --hard <good-sha>
docker compose build scanner
```

**Pause scheduled runs immediately:**

```bash
sudo systemctl disable --now momentum-scanner.timer
```

**Emergency: temporarily re-enable GitHub Actions scheduling.** The old
`scanner.yml` was deleted in this migration. To bring it back as a stopgap,
`git revert` the commit that deleted it (or restore the file from history) and
re-add the `SUPABASE_*` / `DISCORD_*` GitHub secrets. Prefer fixing the VM.
