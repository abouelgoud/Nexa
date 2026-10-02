# Security model

| Control | Implementation |
|---|---|
| Authentication | bcrypt password hashes, HS256 JWT access tokens (`JWT_SECRET` required in production) |
| Authorization | Membership + role checked on every request (`core/deps.py`); RBAC permissions per role |
| Tenant isolation | `tenant_id` on every tenant-owned row, explicit filters, ORM-level automatic tenant criteria, 404 on foreign ids |
| Secrets | Integration credentials encrypted with Fernet (`ENCRYPTION_KEY`), write-only in the API, never in prompts/logs/LLM |
| Tool safety | Allow-list per agent version, JSON Schema validation, table/field permissions, no raw SQL, bounded updates |
| Confirmation | Deterministic yes/no gate for confirmation-required actions; output guard against false success claims |
| SSRF | Integrations and knowledge URLs resolving to private/loopback/link-local addresses are blocked (dev override) |
| Audit | `audit_logs` for every configuration change (redacted) |
| Rate limits | Redis fixed-window limits on auth and test endpoints (in-memory fallback) |
| Input/output validation | Pydantic/Zod on all inputs; business-language errors; `<think>` reasoning stripped from model output |
| Privacy | Per-agent recording/audio/transcript toggles, consent message, retention days enforced by the worker |
| Immutability | DB trigger prevents modifying published agent versions |

Production checklist: set `JWT_SECRET`, `ENCRYPTION_KEY`, `ALLOW_PRIVATE_NETWORK_INTEGRATIONS=false`, LiveKit keys,
TLS termination in front of the API/LiveKit, and restrict CORS (`WEB_ORIGIN`).

Known gaps (next milestones): refresh tokens / httpOnly cookie sessions, webhook signature verification for
carrier callbacks, field-level encryption of transcripts, per-tenant API keys, PostgreSQL row-level security as a
second enforcement layer.
