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

export OPENAI_API_KEY="${EM2MEM_EXTERNAL_OPENAI_API_KEY:-${OPENAI_API_KEY}}"
export OPENAI_BASE_URL="${EM2MEM_EXTERNAL_OPENAI_BASE_URL:-${OPENAI_BASE_URL}}"
export EM2MEM_LOCAL_LLM_ENABLED=0
unset EM2MEM_LOCAL_LLM_NON_THINKING EM2MEM_LOCAL_LLM_BASE_URL

exec python online_evidence_worker.py "$@"
