#!/usr/bin/env bash
# Serve a Qwen3 model with vLLM's OpenAI-compatible API on :8000 (GPU host).
set -euo pipefail
MODEL="${1:-Qwen/Qwen3-8B}"
exec vllm serve "$MODEL" \
  --served-model-name "$MODEL" \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len "${MAX_MODEL_LEN:-8192}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.9}" \
  --host 0.0.0.0 --port 8000
