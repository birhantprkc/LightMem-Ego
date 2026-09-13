#!/usr/bin/env bash
set -Eeuo pipefail

cd /app/backend

case "${MODEL_SERVICE:-}" in
  vlm2vec)
    exec python3 online_vlm2vec_embedding_server.py \
      --host "${EM2MEM_VLM2VEC_EMBED_HOST:-0.0.0.0}" \
      --port "${EM2MEM_VLM2VEC_EMBED_PORT:-18091}" \
      --model-path "${EM2MEM_VLM2VEC_MODEL_PATH:?Set EM2MEM_VLM2VEC_MODEL_PATH to a mounted model directory}" \
      --device "${EM2MEM_VLM2VEC_DEVICE:-cuda}" \
      --dtype "${EM2MEM_VLM2VEC_DTYPE:-float16}"
    ;;
  text)
    exec python3 online_qwen3_embedding_server.py
    ;;
  *)
    echo "MODEL_SERVICE must be vlm2vec or text" >&2
    exit 2
    ;;
esac
