#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"
TIMEOUT="${TIMEOUT:-600}"

exec gunicorn main:app \
  --workers "${WORKERS}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --timeout "${TIMEOUT}" \
  --access-logfile - \
  --error-logfile -
