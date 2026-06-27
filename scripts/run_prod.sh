#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${VENV_PYTHON:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Expected a Python interpreter at $VENV_PYTHON. Create the virtualenv and install dependencies first." >&2
  exit 1
fi

cd "$ROOT_DIR"

export APP_ENV="${APP_ENV:-production}"
export SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
export SERVER_PORT="${SERVER_PORT:-8000}"
export LOG_LEVEL="${LOG_LEVEL:-info}"

exec "$VENV_PYTHON" -m uvicorn app.main:create_app \
  --factory \
  --host "$SERVER_HOST" \
  --port "$SERVER_PORT" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level "$LOG_LEVEL"
