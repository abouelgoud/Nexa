# Nexa - the no-code operating system for AI phone agents

Nexa is a multi-tenant SaaS platform for creating, configuring, testing and deploying AI voice agents
**without code**. It is built for Arabic and English from day one: Arabic-English code switching, probabilistic
dialect detection across the Arab world (Saudi/Najdi, Gulf, Egyptian, Levantine, Iraqi, Maghrebi, Sudanese,
Yemeni, Libyan, MSA, …), original + normalized transcripts, and local/self-hosted AI (vLLM + Qwen3, Whisper,
Piper) behind replaceable provider interfaces.

The first template is **doctor appointment booking**, but the runtime is generic: templates are configuration
(agent definition + tools + workflow) on top of the same platform.

## Quick start

```bash
cp .env.example .env
docker compose up --build                  # web :3000, API :8000 (OpenAPI at /docs), LiveKit :7880
docker compose --profile gpu up --build    # + vLLM serving Qwen3 for "AI decides" (agent) mode
```

Then open http://localhost:3000 and:

1. **Register** (creates your user and first business/tenant).
2. **Create agent → Doctor appointment booking**.
3. **Integrations → Use demo clinic database → Create actions & workflow** (connects the bundled clinic PostgreSQL
   database with table/field permissions and creates the booking actions + visual workflow).
4. **General**: languages (Arabic + English), dialect behaviour, code switching, greeting, voice, policies.
5. **Workflow**: inspect/edit the conversation visually (React Flow).
6. **Testing**: start a call and speak (push-to-talk) or type, e.g. `السلام عليكم، أبغى أحجز موعد جلدية.` →
   `لا` → `الأول` → your phone → `نعم`. Watch language, dialect, intent, tool calls and workflow state live.
   The booking is written to the clinic database only after you confirm.
7. **Calls**: inspect the transcript (original + normalized), every action execution, the workflow path and timeline.
8. **Publish** once the checklist is green - a new immutable version.
9. **Phone**: connect a number from a SIP carrier to call the agent from a real phone (see `docs/telephony.md`).
10. Create another agent (e.g. *Restaurant reservations*) - no code.

Workflow mode runs fully without an LLM; agent mode (LLM chooses actions) needs the `gpu` (vLLM) or `cpu-llm`
(Ollama) profile.

### Local development without Docker

On macOS, one command installs what's missing (Homebrew), creates the databases and runs the API and web app:

```bash
scripts/dev-mac.sh            # then open http://localhost:3000
```

Or manually:

```bash
# API (Python 3.11+, PostgreSQL 16 with pgvector, Redis optional)
cd apps/api && pip install -e '.[dev]'
alembic upgrade head && uvicorn nexa.main:app --reload --port 8000
# Web
npm install && npm run dev            # proxies /api to API_INTERNAL_URL (default http://localhost:8000)
# Worker
PYTHONPATH=apps/worker python -m nexa_worker.main
# Demo clinic DB: psql -d clinic_demo -f infrastructure/postgres/clinic_demo.sql
```

## Tests

```bash
cd apps/api && pytest                 # needs PostgreSQL (TEST_DATABASE_ADMIN_URL), demo clinic DB for integration tests
npm test                              # Zod schema sync + workflow validation (vitest)
npm run typecheck && npm run lint && npm run build
```

Backend coverage includes agent schema, tool validation, workflow execution, tenant authorization, tool permissions,
Arabic and date/time normalization, the REST connector, agent versioning, and integration tests for
Agent → LLM → Tool, Agent → Database, Agent → REST API, Workflow → Tool and Call → Agent → Tool, plus provider
adapters (vLLM/Qwen3 tool calling, Whisper, Piper) and the real-time voice runtime bridge.

## Documentation

* [Architecture](docs/architecture.md) - components, tenancy, versioning, tools, workflow engine, runtime
* [Milestones & status](docs/milestones.md) - what is implemented and verified, what is next
* [Telephony](docs/telephony.md) - WebRTC testing, SIP numbers, transfers
* [Security](docs/security.md)
* [LLM server](services/llm-server/README.md), [voice runtime](services/voice-runtime/README.md)

## Repository

```
apps/        api (FastAPI + nexa package) · web (Next.js) · worker (jobs)
packages/    agent-schema (Zod + JSON Schema) · shared-types · ui · workflow-engine
services/    voice-runtime (LiveKit Agents) · stt (Whisper) · tts (Piper) · llm-server (vLLM/Qwen3)
infrastructure/  docker · postgres (+ demo clinic DB) · livekit · monitoring (Prometheus/Grafana)
```
