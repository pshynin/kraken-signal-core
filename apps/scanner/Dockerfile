# ── Crypto Momentum Alert Copilot — Scanner ───────────────────────────────────
# python:3.12-slim base · non-root user · no dev deps
#
# Build:  docker build -t kraken-scanner .
# Run:    docker run --env-file .env kraken-scanner
# Dry:    docker run --env-file .env kraken-scanner --dry-run

FROM python:3.12-slim

LABEL org.opencontainers.image.title="kraken-signal-scanner" \
      org.opencontainers.image.description="Crypto Momentum Alert Copilot — Scanner" \
      org.opencontainers.image.source="https://github.com/MomentumCopilot/kraken-signal-core"

WORKDIR /app

# ── 1. System deps (none beyond base slim) ────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Python deps (cached layer — only rebuilt when requirements.txt changes) ─
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── 3. Copy scanner source — PYTHONPATH makes it importable without pip install ─
COPY scanner/ ./scanner/
ENV PYTHONPATH=/app

# ── 4. Non-root user ──────────────────────────────────────────────────────────
RUN useradd --no-create-home --no-log-init --uid 1001 scanner_user
USER scanner_user

# ENTRYPOINT lets callers append flags: docker run ... kraken-scanner --dry-run
ENTRYPOINT ["python", "-m", "scanner.main"]
