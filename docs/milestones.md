# Milestones and status

Legend: ✅ implemented and verified by automated tests and/or a real run · 🟡 implemented, verified only partially
(see notes) · ⏭ next.

## First task - foundation ✅
Monorepo structure, architecture docs, 31-table schema with Alembic migration (`alembic check` clean, upgrade /
downgrade tested), Agent JSON schema (Pydantic + Zod + exported JSON Schema, sync-tested), Docker Compose (all
images built and the default stack run healthy; the browser E2E flow passes against it),
FastAPI and Next.js apps, `.env.example`, provider interfaces (LLM/STT/TTS/Embedding/SIP).

## Milestone 1 - Next.js + FastAPI + PostgreSQL + auth + tenants + agent CRUD ✅
Register/login (JWT, bcrypt), tenants and members with RBAC, tenant isolation (dependency + ORM-level criteria),
audit logs, rate limits, agent CRUD, templates. Tests: `test_tenant_authorization.py`. UI: login, register,
dashboard, agents, new agent, settings.

## Milestone 2 - agent configuration + schema + Qwen/vLLM ✅ / 🟡
Full no-code agent settings (general, languages & dialects, voice, personality, capabilities, policies, handoff,
privacy & consent) validated with the shared Zod schema; versioning with immutable snapshots, publish checklist,
roll back. vLLM/Qwen3 provider (tool calls, Hermes inline fallback, `<think>` stripping, thinking disabled,
streaming) tested against a protocol-level mock 🟡 - not yet run against a real GPU-served Qwen3 in this environment.

## Milestone 3 - Whisper + TTS + browser voice ✅
`services/stt` (faster-whisper) and `services/tts` (Piper, Arabic diacritization) run for real: Arabic and English
speech synthesized by Piper and transcribed correctly by Whisper; a full browser-path voice turn
(audio → Whisper → agent → Piper audio) verified through the API. Browser test console: text, push-to-talk with
barge-in (playback stops when you talk), live debugging. Real-time WebRTC mode (LiveKit + voice runtime with Silero VAD,
turn detection and interruption) verified end to end on the Docker stack: headless Chromium with a fake microphone
playing Arabic speech → LiveKit → voice runtime → Whisper → workflow → Piper reply spoken back and recorded.

## Milestone 4 - tool system + PostgreSQL tools + doctor workflow ✅
Declarative tools, JSON-Schema validation, allow-list, confirmation gate, permission-checked query builder, REST
connector, handoff/end/knowledge built-ins, execution logging, output guard. Doctor template on a separate demo
clinic database. Verified end to end in a browser (Playwright): register → template → demo DB → actions & workflow
→ Arabic conversation → confirmed booking written to the clinic DB → call inspection → publish → second agent.

## Milestone 5 - LiveKit + SIP + virtual phone testing 🟡
`SIPProvider` abstraction, LiveKit SIP implementation (inbound trunk + dispatch rule per number, outbound test calls,
SIP REFER transfer), phone number management UI and API, inbound routing to the published (or test) version,
voice-runtime worker (the same worker verified over WebRTC). Routing and the phone call flow through the runtime
are tested with a fake SIP provider; a call from a real phone needs a carrier SIP trunk and a publicly reachable
LiveKit SIP - not possible in this sandbox.

## Milestone 6 - knowledge base + REST connector + visual workflow builder ✅
PDF/DOCX/TXT/URL/FAQ/text ingestion via the Redis worker (inline fallback), pgvector retrieval with citations,
grounded answers and "I don't know" behaviour; REST connector with auth, mapping and SSRF protection;
React Flow builder with palette, node editors, live validation, save.

## Milestone 7 - analytics + observability + security hardening + production 🟡
Analytics dashboard (calls, answered, completed, transferred, failed, duration, latency, languages, dialects,
intents, outcomes, tool failures), call detail, usage metering (all 8 metrics), Prometheus metrics, Grafana
dashboard, JSON logs, optional OpenTelemetry, retention cleanup. ⏭ Remaining: customer-satisfaction capture,
refresh-token sessions, webhook signature verification, Postgres RLS, Kubernetes manifests, billing.

## Next steps
1. Run agent mode against a real vLLM/Qwen3 GPU deployment and tune prompts/tool descriptions on Arabic dialect
   test sets (add an evaluation harness from recorded test calls).
2. Connect a real SIP number end to end; measure STT/LLM/TTS latency budgets on GPU (CPU Whisper-small is ~3-4 s per turn; the agent turn itself is <100 ms).
3. Neural multilingual embeddings (bge-m3) by default when a GPU is present; model-based dialect classifier.
4. SMS/WhatsApp/email executors, CRM/ERP/HIS connectors, recording storage (S3) when enabled.
