#!/usr/bin/env bash
set -euo pipefail

echo "==> Database URL: ${DATABASE_URL}"

# Ensure the data directory exists and is writable
mkdir -p /app/data

# Run Alembic migrations (uses the same DATABASE_URL env var)
echo "==> Running Alembic migrations..."
alembic upgrade head
echo "==> Migrations complete."

# Hand off to the CMD (streamlit, worker, or whatever was passed)
echo "==> Starting: $*"
exec "$@"