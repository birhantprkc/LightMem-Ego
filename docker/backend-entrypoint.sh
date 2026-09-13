#!/usr/bin/env bash
set -Eeuo pipefail

cd /app/backend
mkdir -p online_sessions online_tasks runtime logs

exec python -m uvicorn api_server:app \
  --host "${EM2MEM_API_HOST:-0.0.0.0}" \
  --port "${EM2MEM_API_PORT:-8000}"
