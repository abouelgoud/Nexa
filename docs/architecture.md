# Architecture

Nexa is a **generic platform + templates + configuration + tools + workflows + integrations**.
No industry has its own code path: the Doctor Appointment template is pure configuration.

```
                         Next.js web app (no-code builder, test console, analytics)
                                         │  REST (OpenAPI at /docs)
                                         ▼
                 FastAPI  ── auth / RBAC / tenant isolation / audit / rate limits
                    │
        ┌───────────┼─────────────────────────────┬──────────────────────┐
        ▼           ▼                             ▼                      ▼
  Agent config   Workflow engine            Knowledge (RAG)        Integrations
  + versions     (deterministic graph)      parse→chunk→embed      (encrypted creds)
        │           │                         →pgvector                  │
        └───────────┴──────────┬──────────────────┘                      │
                               ▼                                         │
              ConversationRuntime (VoiceSession)  ◄── one implementation for web + phone
              normalize → language/dialect → policies → workflow | LLM+tools → output guard
                               │                                         │
                 ┌─────────────┼─────────────┐                           │
                 ▼             ▼             ▼                           ▼
            STTProvider   LLMProvider   TTSProvider               Tool executor
            (Whisper)     (vLLM/Qwen3)  (Piper)          validate → permission → confirm → run → log
                                                          ┌──────────┬──────────┬───────────┐
                                                          ▼          ▼          ▼           ▼
                                                     PostgreSQL   REST APIs   Handoff   Knowledge
```

Telephony and real-time audio:

```
PSTN / mobile ─► SIP carrier (Twilio/Telnyx/…) ─► LiveKit SIP ─┐
                                                               ├─► LiveKit room ─► voice-runtime worker
Browser ──────────────── WebRTC ───────────────────────────────┘    (VAD, turn detection, barge-in,
                                                                     STT/TTS adapters) ─► ConversationRuntime
```

## Repository layout

| Path | Contents |
|---|---|
| `apps/api` | FastAPI app and the shared `nexa` Python package (models, runtime, tools, workflow engine, providers) |
| `apps/web` | Next.js 16 + Tailwind v4 + TanStack Query + React Hook Form + Zod + React Flow |
| `apps/worker` | Redis job consumer (document ingestion) and retention cleanup |
| `packages/agent-schema` | Zod mirror of the Pydantic definitions + exported JSON Schemas (sync-tested) |
| `packages/workflow-engine` | Node catalog and client-side workflow validation for the builder |
| `packages/shared-types` | API response types |
| `packages/ui` | shadcn-style UI components |
| `services/voice-runtime` | LiveKit Agents worker for real-time phone/WebRTC calls |
| `services/stt` | faster-whisper (Whisper large-v3) with an OpenAI-compatible transcription API |
| `services/tts` | Piper voices (Arabic with automatic diacritization, English) |
| `services/llm-server` | vLLM/Qwen3 serving notes and script |
| `infrastructure` | Dockerfiles, Postgres init + demo clinic DB, LiveKit, Prometheus/Grafana |

## Multi-tenancy

* Every tenant-owned table has `tenant_id` (mixin `TenantScoped`) with an index and FK.
* `get_tenant_context` verifies the user's membership for the `X-Tenant-ID` header on **every** request and
  returns the role; `require("<permission>")` enforces RBAC (owner/admin/editor/viewer).
* Safety net: once a request is bound to a tenant, an ORM `do_orm_execute` hook adds
  `tenant_id = :tenant` criteria to **every** SELECT on tenant-scoped models, so a forgotten filter cannot leak data
  (tested in `test_tenant_authorization.py`). Routes still filter explicitly.
* Cross-tenant ids return 404 (no existence leak).

## Agent definition and versioning

* `AgentDefinition` (Pydantic, `nexa/schemas/agent_definition.py`) is the contract; the Zod schema mirrors it and a
  test compares fields/enums with the exported JSON Schema.
* `agents.draft_config` is the editable draft. **Publishing** (after the checklist passes) creates an
  `agent_versions` row whose `config` is a self-contained snapshot: the definition **plus resolved tool definitions
  (with tool version ids) and the workflow graph**. Browser tests snapshot the draft as `kind=test` (deduplicated by hash).
* A PostgreSQL trigger rejects any UPDATE of a version's config/hash/number: published versions are immutable even
  for direct SQL. Calls reference exactly one `agent_version_id`. Roll back = point production at an older version.
* `agent_languages`, `agent_voices`, `agent_rules` are normalized projections of each version for querying.

## Conversation runtime

`nexa/runtime/session.py` (`ConversationRuntime` + serializable `VoiceSession`) runs one turn:

1. Keep `original_text`; produce `normalized_text` (digits, tatweel, punctuation - names untouched).
2. Detect language (word-level script ratio → Arabic/English/code-switching) and dialect (probabilistic lexicon
   scores accumulated across the call; never asked from the caller).
3. Deterministic policies first: explicit human requests → transfer; accepted handoff offers.
4. **Workflow mode**: the graph engine drives the call (LLM optional for fallback understanding).
   **Agent mode**: the LLM chooses tools; the backend validates/gates/executes them.
5. Output guard: a reply that claims "booked/cancelled/تم الحجز…" without a successful write action in this turn is
   replaced - the agent never claims success the external system did not confirm.
6. Persist messages, transcripts, tool executions, workflow execution, call events, usage and metrics.

State lives in `conversations.state`, so any API or voice worker can continue a call (row-locked per turn).

## Tool system

* Declarative `ToolDefinition`: name, description, JSON Schema inputs, `requires_confirmation`, executor config.
* Executors: `database` (generic get/search/create/update/delete), `rest_api` (no-code connector),
  `transfer_call`, `end_call`, `knowledge_search`. Categories: database, REST, calendar, CRM, SMS, email, WhatsApp,
  voice, workflow, human handoff, knowledge (SMS/email/WhatsApp executors are future work).
* Only tools in the call's agent version are callable. Arguments are coerced (Arabic digits, dates), validated with
  JSON Schema, then executed server-side with credentials decrypted in memory. The LLM sees name, description and
  inputs only - never configuration or secrets.
* **Confirmation**: in agent mode a confirmation-required tool runs only if the same tool+arguments were proposed in
  the previous turn and the caller's current utterance is a yes (deterministic Arabic/English lexicon). In workflow
  mode a tool node names the Confirm step whose "yes" it requires.
* **Database**: LLM → structured tool → permission validator (table operations + field read/write/deny) →
  SQLAlchemy Core query builder (identifiers checked against the live schema, values bound and type-coerced) →
  database. Updates/deletes must have filters; affected rows are bounded; constraint violations map to business errors.
* **REST**: base URL + auth (bearer/API key/basic) from encrypted credentials, path params, query/body templating
  with dotted mapping (`customer.fullName ← {{name}}`), response mapping (`data.items[].id`), timeouts, size limits
  and SSRF protection (private networks blocked unless explicitly allowed).
* Every execution is logged in `tool_executions` (redacted) and metered.

## Workflow engine

Deterministic graph (`nexa/workflow/engine.py`) with nodes Start, Say, Ask (intent branches), Collect
(text/phone/date/time/number/choice with prefill and retries), Condition (safe AST-whitelisted expressions),
Tool, Knowledge Search, Transfer, Wait, Confirm (yes/no), End. Choice matching combines date/time matching,
ordinals, Arabic-folded label/keyword matching, and an optional LLM fallback.

## Knowledge base

PDF/DOCX/TXT/URL/FAQ/text → parse → chunk (FAQ entries atomic) → embed (`EmbeddingProvider`) → `document_chunks`
(pgvector) → hybrid retrieval (cosine + lexical overlap on Arabic-folded text, score threshold) with internal
citations (document/chunk ids). Answers are generated only from retrieved passages; with no passage above the
threshold the agent says it does not know (and offers a human).

## Providers

`LLMProvider` (`generate`, `stream`, `generate_with_tools`), `STTProvider`, `TTSProvider`, `EmbeddingProvider`,
`SIPProvider` - all built in `nexa/providers/registry.py` from settings. `LOCAL_AI=true` uses vLLM/Qwen3, Whisper,
Piper; cloud providers plug in without touching callers.

## Observability

Prometheus metrics (`/metrics`): STT, LLM total and time-to-first-token, TTS, end-to-end turn and tool latency
histograms; tool failures, calls, API errors. JSON structured logs. OpenTelemetry tracing when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set. Grafana dashboard provisioned under `infrastructure/monitoring`.
