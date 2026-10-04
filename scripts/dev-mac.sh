#!/usr/bin/env bash
# Nexa on macOS without Docker: the whole platform runs natively.
#
#   scripts/dev-mac.sh                          everything: database, API, web app, local LLM (Ollama + Qwen3),
#                                               speech recognition (Whisper), voices (Piper + natural voices with
#                                               cloning on the Apple Silicon GPU), LiveKit and the live-call worker
#   scripts/dev-mac.sh --llm qwen3:8b           larger LLM, roughly half as fast (default qwen3:4b-instruct)
#   scripts/dev-mac.sh --voice-model omnivoice  natural voices with OmniVoice instead of Chatterbox (non-commercial)
#   scripts/dev-mac.sh --no-llm                 use an LLM you run elsewhere (set LLM_BASE_URL / LLM_MODEL)
#   scripts/dev-mac.sh --no-voice               skip speech and live calls (text testing only, starts fastest)
#   scripts/dev-mac.sh --small-pc               for 8 GB computers: smaller Whisper (a bit less accurate), no natural/cloned
#                                               voices (the standard voice still works). ~4.5 GB with the LLM loaded,
#                                               ~2.5 GB once it is idle and unloaded (default setup: ~5 GB / ~3 GB).
#   scripts/dev-mac.sh --dev                    for changing the code: web app and API reload on save (uses more memory)
#   scripts/dev-mac.sh --setup-only             install and set up, don't start anything
#   scripts/dev-mac.sh --no-brew                use PostgreSQL (pgvector), Python 3.11/3.12, Node, livekit-server
#                                               and ollama you installed yourself
#
# Then open http://localhost:3000 and register an account. Ctrl+C stops everything. Logs are in .dev/*.log.
# The first run downloads several GB of models (LLM ~5 GB, voices ~3 GB, Whisper ~1.6 GB). Compatible with bash 3.2.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/apps/api"
STATE_DIR="$ROOT/.dev"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
STT_PORT=8001
TTS_PORT=8002
NEURAL_PORT=8004
LIVEKIT_PORT=7880
OLLAMA_PORT=11434
# Light and accurate enough for calls: ~2.1 GB in memory, and it got all our Arabic booking/answer/intent checks
# right (qwen2.5:1.5b and qwen3:1.7b did not). No hidden reasoning pass, which a phone call can't wait for.
LLM="${LLM:-qwen2.5:3b}"
VOICE_MODEL="${VOICE_MODEL:-chatterbox}"
SETUP_ONLY=0
DEV_MODE=0
WITH_NATURAL=1
USE_BREW=1
WITH_LLM=1
WITH_VOICE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --setup-only) SETUP_ONLY=1 ;;
    --dev) DEV_MODE=1 ;;
    --small-pc) WITH_NATURAL=0; WHISPER_MODEL="${WHISPER_MODEL:-small}" ;;
    --no-brew) USE_BREW=0 ;;
    --no-llm) WITH_LLM=0 ;;
    --no-voice) WITH_VOICE=0 ;;
    --llm) LLM="${2:?--llm needs a model name, e.g. qwen3:4b-instruct}"; shift ;;
    --llm=*) LLM="${1#--llm=}" ;;
    --voice-model) VOICE_MODEL="${2:?--voice-model needs chatterbox or omnivoice}"; shift ;;
    --voice-model=*) VOICE_MODEL="${1#--voice-model=}" ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
trap 'printf "\n\033[1;31mError:\033[0m a step failed (scripts/dev-mac.sh line %s). See the output above.\n" "$LINENO" >&2' ERR

mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------------------------------
step "Checking prerequisites"
if [ "$USE_BREW" = 1 ]; then
  [ "$(uname -s)" = "Darwin" ] || die "This script is for macOS. Use --no-brew on other systems, or Docker."
  command -v brew >/dev/null 2>&1 || die "Homebrew is required: https://brew.sh (or re-run with --no-brew)."

  brew_install() {
    if brew list --formula "$1" >/dev/null 2>&1; then info "$1 already installed"
    else info "installing $1"; brew install "$1"; fi
  }

  brew_install pgvector
  # pgvector is built for specific PostgreSQL versions (it ships lib/postgresql@NN for each one). Use one you
  # already have if possible, otherwise the newest it supports.
  PG_SUPPORTED="$( (ls -d "$(brew --prefix pgvector)"/lib/postgresql@* 2>/dev/null | xargs -n1 basename 2>/dev/null;
                    brew deps --include-build --direct pgvector 2>/dev/null) | grep -E '^postgresql@[0-9]+$' | sort -u -t@ -k2 -n || true)"
  [ -n "$PG_SUPPORTED" ] || die "Could not find which PostgreSQL version pgvector supports (brew info pgvector)."
  PG_FORMULA=""
  for formula in $PG_SUPPORTED; do
    if brew list --formula "$formula" >/dev/null 2>&1; then PG_FORMULA="$formula"; fi
  done
  [ -n "$PG_FORMULA" ] || PG_FORMULA="$(echo "$PG_SUPPORTED" | tail -1)"
  brew_install "$PG_FORMULA"
  brew_install python@3.12
  command -v node >/dev/null 2>&1 || brew_install node
  [ "$WITH_VOICE" = 1 ] && brew_install livekit
  if [ "$WITH_LLM" = 1 ] && ! command -v ollama >/dev/null 2>&1; then brew_install ollama; fi

  PG_BIN="$(brew --prefix "$PG_FORMULA")/bin"
  info "using $PG_FORMULA"
  # Another PostgreSQL service on port 5432 would keep this one from starting (and lacks pgvector).
  OTHER_PG="$(brew services list 2>/dev/null | awk -v want="$PG_FORMULA" \
    '$2 == "started" && $1 ~ /^postgresql(@[0-9]+)?$/ && $1 != want {print $1}' || true)"
  if [ -n "$OTHER_PG" ]; then
    info "another PostgreSQL is running: $(echo $OTHER_PG). It uses port 5432, which $PG_FORMULA needs."
    answer=n
    if [ -t 0 ]; then
      printf '    Stop it so Nexa can use %s? Its data is kept; restart it any time with brew services start. [y/N] ' "$PG_FORMULA"
      read -r answer || answer=n
    fi
    case "$answer" in
      y|Y|yes|YES)
        for other in $OTHER_PG; do info "stopping $other"; brew services stop "$other" >/dev/null; done
        brew services stop "$PG_FORMULA" >/dev/null 2>&1 || true  # may have failed to start while the port was taken
        ;;
      *) die "Stop the other PostgreSQL first (brew services stop $(echo $OTHER_PG)), then run this script again." ;;
    esac
  fi
  if ! brew services list | grep -E "^${PG_FORMULA}[[:space:]]+started" >/dev/null; then
    info "starting $PG_FORMULA"
    brew services start "$PG_FORMULA" >/dev/null
  fi
else
  PG_BIN="${PG_BIN:-$(dirname "$(command -v psql 2>/dev/null || echo /usr/bin/psql)")}"
fi

PSQL="$PG_BIN/psql"
[ -x "$PSQL" ] || die "psql not found in $PG_BIN (set PG_BIN=/path/to/postgres/bin)."

PYTHON=""
for candidate in python3.13 python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$(command -v "$candidate")"; break; fi
done
if [ -z "$PYTHON" ] && [ "$USE_BREW" = 1 ]; then PYTHON="$(brew --prefix python@3.12)/bin/python3.12"; fi
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || die "Python 3.11+ is required (brew install python@3.12)."
command -v npm >/dev/null 2>&1 || die "Node.js 20+ is required (brew install node)."
if [ "$WITH_VOICE" = 1 ]; then
  command -v livekit-server >/dev/null 2>&1 || die "livekit-server is required for live calls (brew install livekit), or use --no-voice."
fi
if [ "$WITH_LLM" = 1 ]; then
  command -v ollama >/dev/null 2>&1 || die "Ollama is required for the local LLM (brew install ollama), or use --no-llm."
fi
# Speech services use Python 3.11/3.12: the voice models don't support newer versions yet.
SPEECH_PYTHON=""
for candidate in python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then SPEECH_PYTHON="$(command -v "$candidate")"; break; fi
done
if [ -z "$SPEECH_PYTHON" ] && [ "$USE_BREW" = 1 ]; then SPEECH_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"; fi
if [ "$WITH_VOICE" = 1 ]; then
  [ -n "$SPEECH_PYTHON" ] && [ -x "$SPEECH_PYTHON" ] || die "Python 3.11 or 3.12 is required for speech (brew install python@3.12)."
fi
info "python: $PYTHON"
info "node:   $(node --version)"

# ---------------------------------------------------------------------------------------------
step "Waiting for PostgreSQL"
# Connects as your macOS user (the Homebrew superuser). Override with PGUSER/PGHOST/PGPASSWORD if needed.
for _ in $(seq 1 30); do
  if "$PSQL" -d postgres -Atqc "SELECT 1" >/dev/null 2>&1; then break; fi
  sleep 1
done
"$PSQL" -d postgres -Atqc "SELECT 1" >/dev/null 2>&1 \
  || die "Cannot connect to PostgreSQL as '$(whoami)'. Is it running? (brew services list; logs: $(brew --prefix 2>/dev/null)/var/log/$PG_FORMULA.log)"
SERVER_MAJOR="$("$PSQL" -d postgres -Atqc "SELECT current_setting('server_version_num')::int / 10000")"
info "connected to PostgreSQL $SERVER_MAJOR"
if [ "$USE_BREW" = 1 ] && [ "$SERVER_MAJOR" != "${PG_FORMULA#postgresql@}" ]; then
  LISTENER="$(lsof -nP -iTCP:5432 -sTCP:LISTEN 2>/dev/null | awk 'NR == 2 {print $1 " (pid " $2 ")"}')"
  die "Port 5432 is taken by another PostgreSQL $SERVER_MAJOR${LISTENER:+ - $LISTENER}, so $PG_FORMULA (which has pgvector) could not start.
       Stop it first: Postgres.app -> Stop; Docker -> docker compose down; Homebrew -> brew services stop <name>.
       Then run this script again."
fi

sql() { "$PSQL" -v ON_ERROR_STOP=1 -q "$@"; }

step "Creating databases (safe to re-run)"
sql -d postgres <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexa') THEN
    CREATE ROLE nexa LOGIN PASSWORD 'nexa' CREATEDB;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clinic_agent') THEN
    CREATE ROLE clinic_agent LOGIN PASSWORD 'clinic_agent';
  END IF;
END $$;
SQL
for db in nexa clinic_demo; do
  if [ "$("$PSQL" -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = '$db'")" != "1" ]; then
    info "creating database $db"
    sql -d postgres -c "CREATE DATABASE $db"
  fi
done
sql -d nexa -c "ALTER DATABASE nexa OWNER TO nexa" -c "ALTER SCHEMA public OWNER TO nexa"
if ! PGV_ERR="$(sql -d nexa -c "CREATE EXTENSION IF NOT EXISTS vector" 2>&1)"; then
  printf '    %s\n' "$PGV_ERR"
  die "pgvector is not installed for PostgreSQL $SERVER_MAJOR. Fix: brew reinstall pgvector (it supports: $(echo ${PG_SUPPORTED:-see brew info pgvector})), then run this script again."
fi
info "platform database: nexa (pgvector enabled)"

sql -d clinic_demo -f "$ROOT/infrastructure/postgres/clinic_demo.sql" 2>&1 | grep -v NOTICE || true
sql -d clinic_demo <<'SQL'
GRANT CONNECT ON DATABASE clinic_demo TO clinic_agent;
GRANT USAGE ON SCHEMA clinic TO clinic_agent;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA clinic TO clinic_agent;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA clinic TO clinic_agent;
SQL
info "demo clinic database: clinic_demo"

# ---------------------------------------------------------------------------------------------
step "Python environment for the API"
VENV="$API_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  info "creating $VENV"
  "$PYTHON" -m venv "$VENV"
fi
STAMP="$STATE_DIR/api-deps.sha"
CURRENT="$(shasum "$API_DIR/pyproject.toml" | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$CURRENT" ]; then
  info "installing API dependencies (first run takes a few minutes)"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e "${API_DIR}[dev]"
  echo "$CURRENT" > "$STAMP"
else
  info "dependencies up to date"
fi

step "Node packages for the web app"
if [ ! -d "$ROOT/node_modules" ] || [ "$ROOT/package-lock.json" -nt "$ROOT/node_modules/.package-lock.json" ]; then
  (cd "$ROOT" && npm install --no-audit --no-fund)
else
  info "node_modules up to date"
fi

# Creates/updates a virtualenv only when its requirements change.
pyenv() {  # name python requirement-args...
  local name="$1" py="$2"; shift 2
  local venv="$STATE_DIR/$name" stamp="$STATE_DIR/$name.sha" want arg
  want="$(for arg in "$@"; do echo "$arg"; if [ -f "$arg" ]; then cat "$arg"; elif [ -f "$arg/pyproject.toml" ]; then cat "$arg/pyproject.toml"; fi; done | shasum | cut -d' ' -f1)"
  [ -x "$venv/bin/python" ] || "$py" -m venv "$venv"
  if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$want" ]; then
    info "installing $name (first run takes a few minutes)"
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q "$@"
    echo "$want" > "$stamp"
  else
    info "$name up to date"
  fi
}

if [ "$WITH_VOICE" = 1 ]; then
  step "Speech services"
  pyenv stt "$SPEECH_PYTHON" -r "$ROOT/services/stt/requirements.txt"
  pyenv tts "$SPEECH_PYTHON" -r "$ROOT/services/tts/requirements.txt"
  pyenv voice-runtime "$SPEECH_PYTHON" -e "$API_DIR" -r "$ROOT/services/voice-runtime/requirements.txt"
  if [ ! -f "$STATE_DIR/silero.ok" ]; then
    info "downloading the voice activity model"
    (cd "$ROOT/services/voice-runtime" && "$STATE_DIR/voice-runtime/bin/python" -m nexa_voice.main download-files >/dev/null 2>&1) \
      && touch "$STATE_DIR/silero.ok" || info "could not download it now; the call worker will retry"
  fi
  if [ "$WITH_NATURAL" = 1 ]; then
    info "natural voices ($VOICE_MODEL)"
    "$ROOT/scripts/voice-mac.sh" --model "$VOICE_MODEL" --setup-only | sed 's/^/    /'
  fi
fi

if [ "$WITH_LLM" = 1 ]; then
  step "Local LLM ($LLM with Ollama)"
  if ! curl -sf "http://localhost:$OLLAMA_PORT/api/version" >/dev/null 2>&1; then
    info "starting Ollama"
    # One model, one conversation at a time, 4k context: keeps Ollama's memory to the model itself.
    (OLLAMA_KEEP_ALIVE=30m OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=4096 \
      ollama serve > "$STATE_DIR/ollama.log" 2>&1 &)
    for _ in $(seq 1 30); do curl -sf "http://localhost:$OLLAMA_PORT/api/version" >/dev/null 2>&1 && break; sleep 1; done
  fi
  curl -sf "http://localhost:$OLLAMA_PORT/api/version" >/dev/null 2>&1 || die "Ollama did not start (see .dev/ollama.log)."
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$LLM"; then info "$LLM already downloaded"
  else info "downloading $LLM (once)"; ollama pull "$LLM"; fi
  # Load the model now so the first caller doesn't wait; it is freed after 30 idle minutes.
  (curl -sf "http://localhost:$OLLAMA_PORT/api/generate" -d "{\"model\": \"$LLM\", \"keep_alive\": \"30m\"}" \
    >/dev/null 2>&1 &)
fi

# ---------------------------------------------------------------------------------------------
# Local settings. The repo-root .env (if any) is for Docker and is not read here.
export ENVIRONMENT=development
export DATABASE_URL="postgresql+asyncpg://nexa:nexa@localhost:5432/nexa"
export DEMO_CLINIC_DATABASE_URL="postgresql://clinic_agent:clinic_agent@localhost:5432/clinic_demo"
export ALLOW_PRIVATE_NETWORK_INTEGRATIONS=true
export JOBS_INLINE=true            # process documents in the API instead of a Redis worker
export SIP_PROVIDER=none
if [ "$WITH_LLM" = 1 ]; then
  export LLM_PROVIDER=local LLM_BASE_URL="http://localhost:$OLLAMA_PORT/v1" LLM_MODEL="$LLM" LLM_API_KEY=not-needed
else
  export LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8010/v1}"
fi
export STT_PROVIDER=whisper STT_BASE_URL="http://localhost:$STT_PORT/v1"
export TTS_PROVIDER=piper TTS_BASE_URL="http://localhost:$TTS_PORT"
export NEURAL_TTS_BASE_URL="http://localhost:$NEURAL_PORT"
export LIVEKIT_URL="ws://localhost:$LIVEKIT_PORT" LIVEKIT_API_URL="http://localhost:$LIVEKIT_PORT"
export LIVEKIT_PUBLIC_URL="ws://localhost:$LIVEKIT_PORT"
export LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=devsecret_devsecret_devsecret_devsecret
MODELS_DIR="$STATE_DIR/models"
export CORS_ORIGINS="[\"http://localhost:$WEB_PORT\"]"
export API_INTERNAL_URL="http://localhost:$API_PORT"
unset NEXT_PUBLIC_API_URL || true

step "Database migrations"
(cd "$API_DIR" && "$VENV/bin/alembic" upgrade head)

if [ "$SETUP_ONLY" = 1 ]; then
  step "Setup complete. Run scripts/dev-mac.sh to start everything."
  exit 0
fi

# ---------------------------------------------------------------------------------------------
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
for port in "$API_PORT" "$WEB_PORT"; do
  port_busy "$port" && die "Port $port is already in use. Stop what is using it (lsof -i :$port) or set API_PORT/WEB_PORT."
done
if [ "$WITH_VOICE" = 1 ]; then
  for port in "$STT_PORT" "$TTS_PORT" "$NEURAL_PORT" "$LIVEKIT_PORT"; do
    port_busy "$port" && die "Port $port is already in use (Docker still running? docker compose down). Stop it first."
  done
fi

PIDS=""
cleanup() {
  printf '\nStopping...\n'
  for pid in $PIDS; do kill "$pid" 2>/dev/null || true; done
  for pid in $PIDS; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# start NAME DIR COMMAND...: runs in the background with its log in .dev/NAME.log
start() {
  local name="$1" dir="$2"; shift 2
  (cd "$dir" && exec "$@") > "$STATE_DIR/$name.log" 2>&1 &
  PIDS="$PIDS $!"
}
# wait_for NAME URL SECONDS: true once URL answers; false if the process died or time ran out
wait_for() {
  local name="$1" url="$2" secs="$3"
  for _ in $(seq 1 "$secs"); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

if [ "$WITH_VOICE" = 1 ]; then
  step "Starting speech and live-call services (logs in .dev/)"
  mkdir -p "$MODELS_DIR"
  cat > "$STATE_DIR/livekit.yaml" <<YAML
port: $LIVEKIT_PORT
bind_addresses: ["127.0.0.1"]
rtc: { tcp_port: 7881, port_range_start: 50000, port_range_end: 50100, use_external_ip: false, node_ip: 127.0.0.1 }
keys: { devkey: devsecret_devsecret_devsecret_devsecret }
logging: { level: info }
YAML
  start livekit "$STATE_DIR" livekit-server --config "$STATE_DIR/livekit.yaml"
  # Whisper runs on the Apple Silicon GPU (mlx) when available; greedy decoding (beam 1) is as accurate on call
  # audio and faster.
  start stt "$ROOT/services/stt" env WHISPER_MODEL="${WHISPER_MODEL:-large-v3-turbo}" WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 WHISPER_BEAM_SIZE="${WHISPER_BEAM_SIZE:-1}" WHISPER_MODEL_DIR="$MODELS_DIR/whisper" \
    "$STATE_DIR/stt/bin/uvicorn" app:app --host 127.0.0.1 --port "$STT_PORT"
  start tts "$ROOT/services/tts" env TTS_ENGINES=piper PIPER_VOICE_DIR="$MODELS_DIR/piper" \
    "$STATE_DIR/tts/bin/uvicorn" app:app --host 127.0.0.1 --port "$TTS_PORT"
  # Natural voices (~3-5 GB) load only when a cloned/natural voice is used and are freed after 10 idle minutes.
  if [ "$WITH_NATURAL" = 1 ]; then
    start voices "$ROOT" env NEURAL_PORT="$NEURAL_PORT" NEURAL_VOICE_DIR="$MODELS_DIR/neural-voices" \
      NEURAL_PRELOAD=background NEURAL_IDLE_MINUTES="${NEURAL_IDLE_MINUTES:-10}" \
      "$ROOT/scripts/voice-mac.sh" --model "$VOICE_MODEL"
  fi
fi

step "Starting the API on http://localhost:$API_PORT"
if [ "$DEV_MODE" = 1 ]; then
  start api "$API_DIR" "$VENV/bin/uvicorn" nexa.main:app --reload --port "$API_PORT"
else
  start api "$API_DIR" "$VENV/bin/uvicorn" nexa.main:app --port "$API_PORT"
fi
wait_for api "http://localhost:$API_PORT/ready" 60 || { tail -30 "$STATE_DIR/api.log"; die "The API did not start (see above)."; }
info "API ready - docs at http://localhost:$API_PORT/docs"

if [ "$WITH_VOICE" = 1 ]; then
  # VOICE_LIGHT: calls run as threads in one process instead of one process (~400 MB) per call.
  start voice-runtime "$ROOT/services/voice-runtime" env VOICE_MAX_CALLS="${VOICE_MAX_CALLS:-4}" VOICE_LIGHT=1 \
    "$STATE_DIR/voice-runtime/bin/python" -m nexa_voice.main dev
fi

step "Starting the web app on http://localhost:$WEB_PORT"
if [ "$DEV_MODE" = 1 ]; then
  start web "$ROOT/apps/web" npx next dev -p "$WEB_PORT"
else
  # The production build uses a fraction of the dev server's memory. Rebuilt only when the web code changed.
  WEB_STAMP="$STATE_DIR/web-build.sha"
  WEB_WANT="$( (cd "$ROOT" && find apps/web/src apps/web/next.config.ts apps/web/package.json packages/*/src \
    -type f -exec shasum {} + 2>/dev/null | sort; echo "$API_INTERNAL_URL") | shasum | cut -d' ' -f1)"
  if [ ! -f "$ROOT/apps/web/.next/BUILD_ID" ] || [ ! -f "$WEB_STAMP" ] || [ "$(cat "$WEB_STAMP")" != "$WEB_WANT" ]; then
    info "building the web app (only after code changes; takes a minute or two)"
    (cd "$ROOT/apps/web" && npx next build > "$STATE_DIR/web-build.log" 2>&1) \
      || { tail -30 "$STATE_DIR/web-build.log"; die "The web app did not build (see above)."; }
    echo "$WEB_WANT" > "$WEB_STAMP"
  fi
  start web "$ROOT/apps/web" npx next start -p "$WEB_PORT"
fi
wait_for web "http://localhost:$WEB_PORT/login" 120 || { tail -30 "$STATE_DIR/web.log"; die "The web app did not start."; }

if [ "$WITH_VOICE" = 1 ]; then
  # Calls placed while the models are still loading are dropped, so wait for them (first start downloads them).
  step "Loading speech models (first start downloads them; can take several minutes)"
  SERVICES="Recognition:$STT_PORT:stt Voices:$TTS_PORT:tts"
  [ "$WITH_NATURAL" = 1 ] && SERVICES="$SERVICES Natural_voices:$NEURAL_PORT:voices"
  for svc in $SERVICES; do
    label="${svc%%:*}"; label="${label//_/ }"; rest="${svc#*:}"; port="${rest%%:*}"; log="${rest#*:}"
    if wait_for "$log" "http://localhost:$port/health" 600; then info "$label ready"
    else info "$label still loading - see .dev/$log.log"; fi
  done
fi

step "Status"
status() {  # label url log
  if curl -sf "$2" >/dev/null 2>&1; then printf '    \033[32mready\033[0m     %s\n' "$1"
  else printf '    \033[33mstarting\033[0m  %s  (models load on first start; see .dev/%s.log)\n' "$1" "$3"; fi
}
status "Web app       http://localhost:$WEB_PORT" "http://localhost:$WEB_PORT/login" web
status "API           http://localhost:$API_PORT/docs" "http://localhost:$API_PORT/ready" api
if [ "$WITH_LLM" = 1 ]; then status "LLM           $LLM (Ollama)" "http://localhost:$OLLAMA_PORT/api/version" ollama; fi
if [ "$WITH_VOICE" = 1 ]; then
  wait_for livekit "http://localhost:$LIVEKIT_PORT" 10 || true
  status "LiveKit       ws://localhost:$LIVEKIT_PORT" "http://localhost:$LIVEKIT_PORT" livekit
  status "Recognition   Whisper ${WHISPER_MODEL:-large-v3-turbo} ($(curl -sf "http://localhost:$STT_PORT/health" | sed -n 's/.*"engine": *"\([^"]*\)".*/\1/p'))" "http://localhost:$STT_PORT/health" stt
  status "Voices        Piper" "http://localhost:$TTS_PORT/health" tts
  if [ "$WITH_NATURAL" = 1 ]; then
    status "Natural voices $VOICE_MODEL (loads when used)" "http://localhost:$NEURAL_PORT/health" voices
  else
    printf '    off       Natural voices (--small-pc)\n'
  fi
fi
printf '\n    Open http://localhost:%s - Ctrl+C stops everything.\n' "$WEB_PORT"
wait
