#!/usr/bin/env bash
# Fast, accurate speech recognition on a Mac: runs only the Whisper service natively, on the Apple Silicon GPU
# (mlx-whisper, large-v3-turbo), while everything else stays in Docker. Docker on macOS can't use the GPU, so the
# containerised recogniser is several times slower.
#
#   scripts/stt-mac.sh                 start it on http://localhost:8011 (installs on first run)
#   scripts/stt-mac.sh --setup-only    install only
#
# Then in .env:   STT_BASE_URL=http://host.docker.internal:8011/v1
# and restart:    docker compose up -d api voice-runtime && docker compose stop stt   (frees ~2 GB)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT/.dev"
PORT="${STT_PORT:-8011}"
SETUP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --setup-only) SETUP_ONLY=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

PY=""
for candidate in python3.12 python3.11; do
  command -v "$candidate" >/dev/null 2>&1 && { PY="$candidate"; break; }
done
if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
  info "installing python@3.12"; brew install python@3.12; PY="$(brew --prefix python@3.12)/bin/python3.12"
fi
[ -n "$PY" ] || die "Python 3.11 or 3.12 is required (brew install python@3.12)."

VENV="$STATE_DIR/stt"
step "Installing the speech recognition service into $VENV"
mkdir -p "$STATE_DIR"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
STAMP="$STATE_DIR/stt.sha"
WANT="$(printf -- '-r\n%s\n' "$ROOT/services/stt/requirements.txt"; cat "$ROOT/services/stt/requirements.txt")"
WANT="$(echo "$WANT" | shasum | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$ROOT/services/stt/requirements.txt"
  echo "$WANT" > "$STAMP"
else
  info "already installed"
fi
if [ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ]; then
  info "Apple Silicon: Whisper will run on the GPU (mlx)."
else
  info "Not an Apple Silicon Mac: Whisper will run on the CPU (no faster than the Docker service)."
fi

[ "$SETUP_ONLY" = 1 ] && { step "Installed. Run scripts/stt-mac.sh to start."; exit 0; }

step "Starting speech recognition on http://localhost:$PORT (Ctrl+C stops)"
info "In .env: STT_BASE_URL=http://host.docker.internal:$PORT/v1, then: docker compose up -d api voice-runtime"
info "The model downloads once on first start (~1.6 GB)."
cd "$ROOT/services/stt"
export WHISPER_MODEL="${WHISPER_MODEL:-large-v3-turbo}" WHISPER_BEAM_SIZE="${WHISPER_BEAM_SIZE:-1}"
export WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-$STATE_DIR/models/whisper}"
exec "$VENV/bin/uvicorn" app:app --host 0.0.0.0 --port "$PORT"
