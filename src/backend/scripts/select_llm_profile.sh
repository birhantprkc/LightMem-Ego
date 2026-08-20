#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-}"

case "$PROFILE" in
  remote|local-qwen35) ;;
  *)
    echo "Usage: scripts/select_llm_profile.sh {remote|local-qwen35}" >&2
    exit 2
    ;;
esac

mkdir -p "$ROOT_DIR/runtime/config"
printf '%s\n' "$PROFILE" > "$ROOT_DIR/runtime/config/llm_profile"
echo "[select_llm_profile] selected profile: $PROFILE"
if [[ "$PROFILE" == "remote" ]]; then
  "$ROOT_DIR/scripts/stop_local_qwen35_server.sh"
fi
echo "[select_llm_profile] restart LLM workers for the selection to take effect"
