#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/llm_profile.sh"

# Refine captions always use the external API values from .env. The local
# Qwen endpoint is reserved for final answer generation in the query worker.
export OPENAI_API_KEY="${EM2MEM_EXTERNAL_OPENAI_API_KEY:-${OPENAI_API_KEY}}"
export OPENAI_BASE_URL="${EM2MEM_EXTERNAL_OPENAI_BASE_URL:-${OPENAI_BASE_URL}}"
export EM2MEM_LOCAL_LLM_ENABLED=0
unset EM2MEM_LOCAL_LLM_NON_THINKING EM2MEM_LOCAL_LLM_BASE_URL

export EM2MEM_MST_REFINE_BACKEND="${EM2MEM_MST_REFINE_BACKEND:-openai}"
export EM2MEM_REFINE_MAX_CONCURRENCY="${EM2MEM_REFINE_MAX_CONCURRENCY:-4}"
export EM2MEM_WORKER_INSTANCE_NAME="${EM2MEM_WORKER_INSTANCE_NAME:-refine}"

echo "[start_online_mst_refine_worker] EM2MEM_WORKER_INSTANCE_NAME=${EM2MEM_WORKER_INSTANCE_NAME}"
echo "[start_online_mst_refine_worker] EM2MEM_MST_REFINE_BACKEND=${EM2MEM_MST_REFINE_BACKEND}"
echo "[start_online_mst_refine_worker] EM2MEM_MST_REFINE_MODEL=${EM2MEM_MST_REFINE_MODEL:-${EM2MEM_VLM_MODEL:-${OPENAI_MODEL:-}}}"
echo "[start_online_mst_refine_worker] EM2MEM_REFINE_MAX_CONCURRENCY=${EM2MEM_REFINE_MAX_CONCURRENCY}"

exec python online_mst_refine_worker.py "$@"
