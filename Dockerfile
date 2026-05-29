# ──────────────────────────────────────────────
# Stage 1: Builder — install deps into an in-project venv
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=2.3.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

ENV PATH="${POETRY_HOME}/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -sSL https://install.python-poetry.org | python3 - && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main --no-root

COPY . .
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main


# ──────────────────────────────────────────────
# Stage 2: Runtime
# ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Single apt layer: poppler + curl + Chromium runtime deps
# Combine everything in one RUN to minimize layer size
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        poppler-utils \
        curl \
        # Playwright Chromium runtime deps (arm64-compatible names)
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2t64 \
        libxshmfence1 \
        libx11-xcb1 \
        fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app .

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL="sqlite+aiosqlite:////app/data/scraper.db" \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Install Chromium — use --with-deps as fallback if the manual libs above
# don't cover everything, but since we already installed them this just
# downloads the browser binary (~150MB)
RUN playwright install chromium

RUN mkdir -p /app/data && chown -R app:app /app /home/app

VOLUME ["/app/data", "/app/config"]

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["streamlit", "run", "src/scraper/ui/app.py"]