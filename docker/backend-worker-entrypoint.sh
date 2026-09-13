#!/usr/bin/env bash
set -Eeuo pipefail

cd /app/backend
mkdir -p online_sessions online_tasks runtime logs

pids=()
names=()

start_worker() {
  local name="$1"
  shift
  echo "[docker-workers] starting ${name}: $*"
  "$@" >"logs/${name}.log" 2>&1 &
  pids+=("$!")
  names+=("$name")
}

stop_workers() {
  local pid
  for pid in "${pids[@]:-}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]:-}"; do
    wait "$pid" 2>/dev/null || true
  done
}

handle_term() {
  stop_workers
  exit 0
}

trap stop_workers EXIT
trap handle_term INT TERM

# These are the same workers selected by scripts/start_online_all_workers.sh,
# but run in the foreground of one container-managed process tree.
start_worker preprocess env EM2MEM_PREPROCESS_CONSUME_STREAM_ASR="${EM2MEM_PREPROCESS_CONSUME_STREAM_ASR:-0}" bash scripts/start_online_worker.sh
start_worker asr bash scripts/start_online_asr_worker.sh --worker-name asr --task-filter voice_question --device "${EM2MEM_ASR_WHISPERX_DEVICE:-cpu}"
start_worker asr_stream bash scripts/start_online_asr_worker.sh --worker-name asr_stream --task-filter stream --device "${EM2MEM_STREAM_ASR_WHISPERX_DEVICE:-cpu}"
start_worker stream bash scripts/start_online_stream_worker.sh
start_worker live_ingest bash scripts/start_online_live_ingest_worker.sh
start_worker refine bash scripts/start_online_mst_refine_worker.sh
start_worker consolidation bash scripts/start_online_mst_consolidation_worker.sh
start_worker visual bash scripts/start_online_visual_worker.sh
start_worker memory bash scripts/start_online_memory_worker.sh
start_worker query bash scripts/start_online_query_worker.sh

echo "[docker-workers] all workers started"

while true; do
  for index in "${!pids[@]}"; do
    if ! kill -0 "${pids[$index]}" 2>/dev/null; then
      wait "${pids[$index]}" || true
      echo "[docker-workers] ${names[$index]} exited; stopping worker container" >&2
      exit 1
    fi
  done
  sleep 2
done
