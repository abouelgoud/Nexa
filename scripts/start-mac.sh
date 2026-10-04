#!/usr/bin/env bash
# Nexa on a Mac: every service in Docker, except natural/cloned voices, which run on the Mac itself so they can
# use the Apple GPU (Docker on macOS can't).
#
#   scripts/start-mac.sh                       start everything (Ctrl+C stops the voice service; Docker keeps running)
#   scripts/start-mac.sh --model omnivoice     natural voices with OmniVoice (non-commercial weights)
#   scripts/start-mac.sh --no-build            skip rebuilding the Docker images
#
# Stop everything: Ctrl+C here, then `docker compose down`.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VOICE_PORT="${NEURAL_PORT:-8004}"
BUILD="--build"
VOICE_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) BUILD="" ;;
    --model) VOICE_ARGS+=(--model "${2:?--model needs chatterbox or omnivoice}"); shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
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

# The Docker services reach the voice service on this Mac. Set here so an older .env (which pointed at a GPU
# container) can't override it.
export NEURAL_TTS_BASE_URL="http://host.docker.internal:$VOICE_PORT"
if [ -z "${WHISPER_MODEL:-}" ] && [ -f .env ] && grep -qE '^WHISPER_MODEL=small' .env; then
  info "note: .env sets WHISPER_MODEL=small (less accurate Arabic); remove that line to use large-v3-turbo"
fi

step "Starting the Docker services (first time: builds images and downloads models)"
docker compose up -d $BUILD
for _ in $(seq 1 90); do
  curl -sf "http://localhost:${API_PORT:-8000}/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl -sf "http://localhost:${API_PORT:-8000}/ready" >/dev/null 2>&1 \
  || die "The API did not start. See: docker compose logs api"
info "web app: http://localhost:${WEB_PORT:-3000}   (Docker keeps running after you stop this script)"

step "Starting natural voices on this Mac (port $VOICE_PORT)"
info "Leave this running for cloned/natural voices. Ctrl+C stops it; the rest keeps running in Docker."
exec env NEURAL_PORT="$VOICE_PORT" "$ROOT/scripts/voice-mac.sh" "${VOICE_ARGS[@]+"${VOICE_ARGS[@]}"}"
