#!/usr/bin/env bash
set -euo pipefail

HOST="${EM2MEM_LOCAL_LLM_HOST:-127.0.0.1}"
PORT="${EM2MEM_LOCAL_LLM_PORT:-18100}"
URL="${EM2MEM_LOCAL_LLM_BASE_URL:-http://${HOST}:${PORT}/v1}"

curl -fsS --max-time "${EM2MEM_LOCAL_LLM_HEALTH_TIMEOUT_SECONDS:-5}" "${URL%/}/models"
