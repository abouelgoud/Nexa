#!/usr/bin/env bash
# Nexa on a Mac: every service in Docker, except the two that need the Apple GPU (Docker on macOS can't use it):
# speech recognition (Whisper with mlx) and natural/cloned voices. Those run on the Mac itself.
#
#   scripts/start-mac.sh                       start everything (Ctrl+C stops the Mac services; Docker keeps running)
#   scripts/start-mac.sh --model omnivoice     natural voices with OmniVoice (non-commercial weights)
#   scripts/start-mac.sh --docker-stt          keep speech recognition in Docker (CPU; several times slower)
#   scripts/start-mac.sh --no-build            skip rebuilding the Docker images
#
# Stop everything: Ctrl+C here, then `docker compose down`. Logs of the Mac services: .dev/stt-mac.log and this window.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VOICE_PORT="${NEURAL_PORT:-8004}"
STT_PORT="${STT_PORT:-8011}"
BUILD="--build"
VOICE_ARGS=()
NATIVE_STT=0
[ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ] && NATIVE_STT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) BUILD="" ;;
    --docker-stt) NATIVE_STT=0 ;;
    --model) VOICE_ARGS+=(--model "${2:?--model needs chatterbox or omnivoice}"); shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is required (Docker Desktop: https://www.docker.com/products/docker-desktop)."
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and try again."
cd "$ROOT"
mkdir -p .dev

# The Docker services reach the Mac services through host.docker.internal. Set here so an older .env (which pointed
# at a GPU container or the Docker recogniser) can't override it.
export NEURAL_TTS_BASE_URL="http://host.docker.internal:$VOICE_PORT"
if [ -z "${WHISPER_MODEL:-}" ] && [ -f .env ] && grep -qE '^WHISPER_MODEL=small' .env; then
  info "note: .env sets WHISPER_MODEL=small (less accurate Arabic); remove that line to use large-v3-turbo"
fi

STT_PID=""
cleanup() { [ -n "$STT_PID" ] && kill "$STT_PID" 2>/dev/null; true; }
trap cleanup EXIT

if [ "$NATIVE_STT" = 1 ]; then
  step "Speech recognition on this Mac's GPU (port $STT_PORT)"
  "$ROOT/scripts/stt-mac.sh" --setup-only >/dev/null || die "Could not install speech recognition (run scripts/stt-mac.sh --setup-only to see why)."
  STT_PORT="$STT_PORT" "$ROOT/scripts/stt-mac.sh" > .dev/stt-mac.log 2>&1 &
  STT_PID=$!
  export STT_BASE_URL="http://host.docker.internal:$STT_PORT/v1"
  info "started (log: .dev/stt-mac.log); the model loads in the background (first start downloads ~1.6 GB)"
fi

step "Starting the Docker services (first time: builds images and downloads models)"
if [ "$NATIVE_STT" = 1 ]; then
  docker compose stop stt >/dev/null 2>&1 || true  # replaced by the Mac recogniser; frees ~2 GB
  # shellcheck disable=SC2046
  docker compose up -d $BUILD $(docker compose config --services | grep -vx stt)
else
  docker compose up -d $BUILD
fi
for _ in $(seq 1 90); do
  curl -sf "http://localhost:${API_PORT:-8000}/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl -sf "http://localhost:${API_PORT:-8000}/ready" >/dev/null 2>&1 \
  || die "The API did not start. See: docker compose logs api"
info "web app: http://localhost:${WEB_PORT:-3000}   (Docker keeps running after you stop this script)"

if [ "$NATIVE_STT" = 1 ]; then
  for _ in $(seq 1 300); do
    status="$(curl -sf "http://localhost:$STT_PORT/health" 2>/dev/null || true)"
    case "$status" in *'"ok"'*) break ;; esac
    kill -0 "$STT_PID" 2>/dev/null || die "Speech recognition stopped. See .dev/stt-mac.log"
    sleep 2
  done
  case "$status" in
    *'"mlx"'*) info "speech recognition ready (Apple GPU)" ;;
    *'"ok"'*) info "speech recognition ready (CPU - mlx unavailable, see .dev/stt-mac.log)" ;;
    *) info "speech recognition is still loading its model; calls will recognise speech once it is ready" ;;
  esac
fi

step "Starting natural voices on this Mac (port $VOICE_PORT)"
info "Leave this running for speech recognition and natural/cloned voices. Ctrl+C stops them; Docker keeps running."
NEURAL_PORT="$VOICE_PORT" "$ROOT/scripts/voice-mac.sh" "${VOICE_ARGS[@]+"${VOICE_ARGS[@]}"}"
