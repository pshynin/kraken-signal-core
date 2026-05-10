# ── Crypto Momentum Alert Copilot — Scanner ───────────────────────────────────
# Minimal image for running the Python scanner.
# Full production hardening added in PR 17.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scanner source
COPY scanner/ ./scanner/

# Non-root user for safety
RUN useradd --no-create-home --no-log-init scanner_user
USER scanner_user

CMD ["python", "-m", "scanner.main"]
