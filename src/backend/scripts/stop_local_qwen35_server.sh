#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_PATH="$ROOT_DIR/runtime/workers/local_qwen35.pid"

if [[ ! -f "$PID_PATH" ]]; then
  echo "[stop_local_qwen35_server] no pid file; service is not managed by this project"
  exit 0
fi

PID="$(tr -d '[:space:]' < "$PID_PATH")"
if [[ ! "$PID" =~ ^[0-9]+$ ]] || ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_PATH"
  echo "[stop_local_qwen35_server] removed stale pid file"
  exit 0
fi

COMMAND="$(ps -o command= -p "$PID" 2>/dev/null || true)"
if [[ "$COMMAND" != *"start_local_qwen35_server.sh"* && "$COMMAND" != *"vllm"*"Qwen3.5-9B"* ]]; then
  echo "[stop_local_qwen35_server] refusing to stop unexpected process pid=$PID command=$COMMAND" >&2
  exit 1
fi

PGID="$(ps -o pgid= -p "$PID" | tr -d ' ')"
kill -- "-$PGID"
for _ in $(seq 1 20); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_PATH"
    echo "[stop_local_qwen35_server] stopped pid=$PID"
    exit 0
  fi
  sleep 1
done

echo "[stop_local_qwen35_server] process did not stop within 20 seconds: pid=$PID" >&2
exit 1
