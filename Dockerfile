# ──────────────────────────────────────────────
# Stage 1: Build — install Poetry deps into a venv
# ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# Copy only dependency files first (layer caching)
COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root --only main

# Copy source and install the project itself
COPY . .
RUN poetry install --only main


# ──────────────────────────────────────────────
# Stage 2: Runtime — slim image with system deps
# ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# System deps: poppler (PDF), Playwright/Chromium deps, curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        curl \
        # Chromium runtime deps (Playwright)
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app

WORKDIR /app

# Copy venv + source from builder
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app .

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Install Playwright Chromium browser (cached in image)
RUN playwright install chromium

# Config and data volumes
VOLUME ["/app/config"]

# Switch to non-root
RUN chown -R app:app /app
USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Default: run DB migrations then start Streamlit UI
CMD ["sh", "-c", "alembic upgrade head && streamlit run src/scraper/ui/app.py"]