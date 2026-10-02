#!/usr/bin/env bash
# Nexa local development on macOS without Docker: API + web app + demo clinic database.
#
#   scripts/dev-mac.sh               install what's missing (Homebrew), set up the databases, run API + web
#   scripts/dev-mac.sh --setup-only  install and set up, don't start anything
#   scripts/dev-mac.sh --no-brew     use PostgreSQL (with pgvector), Python 3.11+ and Node you installed yourself
#
# Then open http://localhost:3000 and register an account. Ctrl+C stops everything.
# Not included (use Docker for these): speech services (voice testing), LiveKit, the LLM.
# Text testing and the full booking flow work. Compatible with macOS's bash 3.2.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/apps/api"
STATE_DIR="$ROOT/.dev"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
SETUP_ONLY=0
USE_BREW=1
for arg in "$@"; do
  case "$arg" in
    --setup-only) SETUP_ONLY=1 ;;
    --no-brew) USE_BREW=0 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

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
  # pgvector is built for specific PostgreSQL versions: use the newest one it supports.
  PG_FORMULA="$(brew deps --direct pgvector | grep -E '^postgresql@[0-9]+$' | sort -t@ -k2 -n | tail -1 || true)"
  [ -n "$PG_FORMULA" ] || die "Could not find which PostgreSQL version pgvector supports (brew deps pgvector)."
  brew_install "$PG_FORMULA"
  brew_install python@3.12
  command -v node >/dev/null 2>&1 || brew_install node

  PG_BIN="$(brew --prefix "$PG_FORMULA")/bin"
  info "using $PG_FORMULA"
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
  || die "Cannot connect to PostgreSQL as '$(whoami)'. Is it running? (brew services list)"
info "connected"

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
sql -d nexa -c "CREATE EXTENSION IF NOT EXISTS vector" 2>/dev/null \
  || die "The pgvector extension is not available for this PostgreSQL. With Homebrew, pgvector must match the PostgreSQL version (brew info pgvector)."
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

# ---------------------------------------------------------------------------------------------
# Local settings. The repo-root .env (if any) is for Docker and is not read here.
export ENVIRONMENT=development
export DATABASE_URL="postgresql+asyncpg://nexa:nexa@localhost:5432/nexa"
export DEMO_CLINIC_DATABASE_URL="postgresql://clinic_agent:clinic_agent@localhost:5432/clinic_demo"
export ALLOW_PRIVATE_NETWORK_INTEGRATIONS=true
export JOBS_INLINE=true            # process documents in the API instead of a Redis worker
export SIP_PROVIDER=none
export LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8010/v1}"
export STT_BASE_URL="${STT_BASE_URL:-http://localhost:8001/v1}"
export TTS_BASE_URL="${TTS_BASE_URL:-http://localhost:8002}"
export NEURAL_TTS_BASE_URL="${NEURAL_TTS_BASE_URL:-http://localhost:8004}"
export CORS_ORIGINS="[\"http://localhost:$WEB_PORT\"]"
export API_INTERNAL_URL="http://localhost:$API_PORT"
unset NEXT_PUBLIC_API_URL || true

step "Database migrations"
(cd "$API_DIR" && "$VENV/bin/alembic" upgrade head)

if [ "$SETUP_ONLY" = 1 ]; then
  step "Setup complete. Run scripts/dev-mac.sh to start the API and web app."
  exit 0
fi

# ---------------------------------------------------------------------------------------------
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
port_busy "$API_PORT" && die "Port $API_PORT is already in use (another API?). Stop it or set API_PORT=..."
port_busy "$WEB_PORT" && die "Port $WEB_PORT is already in use. Stop it or set WEB_PORT=..."

API_LOG="$STATE_DIR/api.log"
step "Starting the API on http://localhost:$API_PORT (log: .dev/api.log)"
(cd "$API_DIR" && exec "$VENV/bin/uvicorn" nexa.main:app --reload --port "$API_PORT") > "$API_LOG" 2>&1 &
API_PID=$!

cleanup() {
  printf '\nStopping...\n'
  kill "$API_PID" 2>/dev/null || true
  wait "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -sf "http://localhost:$API_PORT/ready" >/dev/null 2>&1; then break; fi
  kill -0 "$API_PID" 2>/dev/null || { tail -30 "$API_LOG"; die "The API failed to start (see above)."; }
  sleep 1
done
curl -sf "http://localhost:$API_PORT/ready" >/dev/null 2>&1 || { tail -30 "$API_LOG"; die "The API did not become ready."; }
info "API ready - docs at http://localhost:$API_PORT/docs"

step "Starting the web app on http://localhost:$WEB_PORT  (Ctrl+C to stop everything)"
cd "$ROOT/apps/web"
npx next dev -p "$WEB_PORT"
