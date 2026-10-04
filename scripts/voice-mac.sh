#!/usr/bin/env bash
# Natural voices with cloning on a Mac, without an NVIDIA GPU (the same approach as VoiceStudio).
#
# Docker on macOS cannot use the Mac's GPU, so this runs the neural voice service natively, where PyTorch uses
# Apple Silicon's Metal GPU (MPS). On an Intel Mac or without MPS it falls back to the CPU (slow: fine for
# creating voices, too slow for live calls).
#
#   scripts/voice-mac.sh                     Chatterbox Multilingual (MIT: OK for commercial use)
#   scripts/voice-mac.sh --model omnivoice   OmniVoice, VoiceStudio's engine (weights are NON-COMMERCIAL)
#   scripts/voice-mac.sh --setup-only        install only
#
# The service listens on http://localhost:8004. Point the API at it:
#   - API in Docker:  NEURAL_TTS_BASE_URL=http://host.docker.internal:8004 in .env, then
#                     docker compose up -d api voice-runtime
#   - scripts/dev-mac.sh: already uses http://localhost:8004
# The first start downloads the model (Chatterbox ~3 GB, OmniVoice ~2.4 GB plus Whisper ~1.6 GB on first clone).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="$ROOT/services/tts"
STATE_DIR="$ROOT/.dev"
PORT="${NEURAL_PORT:-8004}"
MODEL="chatterbox"
SETUP_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="${2:-}"; shift ;;
    --model=*) MODEL="${1#--model=}" ;;
    --setup-only) SETUP_ONLY=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

case "$MODEL" in
  chatterbox) REQS="$SERVICE_DIR/requirements-neural.txt" ;;
  omnivoice) REQS="$SERVICE_DIR/requirements-omnivoice.txt"
    printf '\n\033[1;33mNote:\033[0m OmniVoice weights are licensed CC-BY-NC (non-commercial use only).\n' ;;
  *) die "Unknown model '$MODEL' (use chatterbox or omnivoice)." ;;
esac

step "Checking Python"
PY=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)'; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  info "installing python@3.12"; brew install python@3.12; PY="$(brew --prefix python@3.12)/bin/python3.12"
fi
[ -n "$PY" ] || die "Python 3.10-3.12 is required (brew install python@3.12)."
info "using $("$PY" --version)"

VENV="$STATE_DIR/voice-$MODEL"
step "Installing the $MODEL voice engine into $VENV"
mkdir -p "$STATE_DIR"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
STAMP="$VENV/.nexa-reqs"
WANT="$(cat "$REQS" "$SERVICE_DIR/requirements.txt" | shasum | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$REQS" fastapi "uvicorn[standard]" python-multipart
  echo "$WANT" > "$STAMP"
else
  info "already installed"
fi

DEVICE="$("$VENV/bin/python" -c 'import torch
print("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")')"
case "$DEVICE" in
  mps) info "Apple Silicon GPU (Metal) detected: voices will render on the GPU." ;;
  cuda) info "NVIDIA GPU detected." ;;
  *) info "No GPU acceleration found: running on the CPU. Creating voices works; live calls will lag." ;;
esac

[ "$SETUP_ONLY" = 1 ] && { step "Installed. Run scripts/voice-mac.sh --model $MODEL to start."; exit 0; }

step "Starting the voice service on http://localhost:$PORT ($MODEL on $DEVICE)"
info "The model loads in the background (downloaded once: a few minutes the first time)."
info "In Docker setups set NEURAL_TTS_BASE_URL=http://host.docker.internal:$PORT in .env. Ctrl+C stops."
cd "$SERVICE_DIR"
export TTS_ENGINES=neural NEURAL_MODEL="$MODEL" NEURAL_DEVICE="${NEURAL_DEVICE:-auto}"
export NEURAL_VOICE_DIR="${NEURAL_VOICE_DIR:-$STATE_DIR/neural-voices}"
# The model (~3-5 GB) starts loading in the background right away (NEURAL_PRELOAD=false: only when first used),
# and its memory is freed after 10 idle minutes; it reloads on the next use.
export NEURAL_PRELOAD="${NEURAL_PRELOAD:-background}" NEURAL_IDLE_MINUTES="${NEURAL_IDLE_MINUTES:-10}"
export PYTORCH_ENABLE_MPS_FALLBACK=1  # run the few operations Metal lacks on the CPU instead of failing
exec "$VENV/bin/uvicorn" app:app --host 0.0.0.0 --port "$PORT"
