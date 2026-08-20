#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${EM2MEM_LOCAL_LLM_VENV:-$ROOT_DIR/.venv_vllm}"
PYTHON_BIN="${EM2MEM_LOCAL_LLM_BOOTSTRAP_PYTHON:-$ROOT_DIR/.venv/bin/python}"
TMP_DIR="${EM2MEM_LOCAL_LLM_TMPDIR:-$ROOT_DIR/.cache/vllm-tmp}"
VLLM_VERSION="${EM2MEM_LOCAL_VLLM_VERSION:-0.26.1rc1.dev306+gcb8104839}"
MODELSCOPE_VERSION="${EM2MEM_LOCAL_MODELSCOPE_VERSION:-1.39.0}"

mkdir -p "$TMP_DIR"
export TMPDIR="$TMP_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --pre --extra-index-url https://wheels.vllm.ai/nightly "vllm==$VLLM_VERSION"
"$VENV_DIR/bin/python" -m pip install "modelscope==$MODELSCOPE_VERSION"

echo "[setup_local_qwen35_env] ready: $VENV_DIR"
"$VENV_DIR/bin/python" - <<'PY'
from importlib.metadata import version
for package in ("vllm", "torch", "transformers", "modelscope"):
    print(f"{package}={version(package)}")
PY
