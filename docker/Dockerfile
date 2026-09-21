# syntax=docker/dockerfile:1
# Multi-stage production Dockerfile for Forge FastAPI + LangGraph Agent Backend

# ── Stage 1: Build & Wheel Compilation ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY python_backend/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# ── Stage 2: Minimal Production Runtime ────────────────────────────────────────
FROM python:3.11-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    FORGE_HOME=/home/forge/.forge

WORKDIR /app

# Install runtime dependencies for Playwright headless Chromium and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built Python packages
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

# Pre-install headless Chromium in shared location with world-readable permissions
RUN playwright install chromium \
    && chmod -R 755 /opt/ms-playwright

# Create non-root unprivileged service user (UID 1000)
RUN groupadd -g 1000 forge \
    && useradd -u 1000 -g forge -m -s /bin/bash forge \
    && mkdir -p /home/forge/.forge /app \
    && chown -R forge:forge /home/forge /app

# Copy application source code
COPY --chown=forge:forge python_backend/ /app/

USER forge

EXPOSE 8765

# Container healthcheck querying FastAPI /health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

ENTRYPOINT ["python", "app.py"]

