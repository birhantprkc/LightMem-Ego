#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${EM2MEM_LOCAL_LLM_VENV:-$ROOT_DIR/.venv_vllm}"
MODEL_ID="${EM2MEM_LOCAL_LLM_MODELSCOPE_ID:-Qwen/Qwen3.5-9B}"
MODEL_DIR="${EM2MEM_LOCAL_LLM_MODEL_PATH:-$ROOT_DIR/models/Qwen3.5-9B}"

if [[ ! -x "$VENV_DIR/bin/modelscope" ]]; then
  echo "[download_local_qwen35_model] missing ModelScope CLI; run scripts/setup_local_qwen35_env.sh first" >&2
  exit 1
fi

mkdir -p "$MODEL_DIR"
"$VENV_DIR/bin/modelscope" download --model "$MODEL_ID" --local_dir "$MODEL_DIR"

if [[ ! -f "$MODEL_DIR/config.json" ]]; then
  echo "[download_local_qwen35_model] download did not produce $MODEL_DIR/config.json" >&2
  exit 1
fi

echo "[download_local_qwen35_model] ready: $MODEL_DIR"
