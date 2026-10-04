/** API response types shared by the web app (mirrors apps/api/nexa/api/schemas.py). */
import type { AgentDefinition, ToolDefinition, WorkflowGraph } from "@nexa/agent-schema";

export type Role = "owner" | "admin" | "editor" | "viewer";

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

export interface User { id: string; email: string; full_name: string; locale: string }
export interface Membership { tenant_id: string; tenant_name: string; role: Role }
export interface TokenResponse { access_token: string; token_type: string; user: User; memberships: Membership[] }

export interface Tenant {
  id: string; name: string; slug: string; industry: string | null; default_timezone: string; plan: string; created_at: string;
}
export interface Member { user_id: string; email: string; full_name: string; role: Role }

export interface Agent {
  id: string; name: string; description: string; industry: string | null; template_key: string | null;
  status: "draft" | "published" | "archived"; published_version_id: string | null; created_at: string; updated_at: string;
}
export interface AgentDetail extends Agent { draft_config: AgentDefinition }

export interface AgentVersion {
  id: string; agent_id: string; version_number: number; kind: "test" | "published"; config_hash: string; notes: string;
  published_at: string | null; created_at: string;
}

export interface ChecklistItem { key: string; label: string; ok: boolean; message: string; severity: "error" | "warning" }
export interface Checklist { ready: boolean; items: ChecklistItem[] }

export interface Template { key: string; name: string; name_ar: string; industry: string; description: string; needs_database: boolean }

export interface Tool {
  id: string; name: string; display_name: string; description: string; category: string; definition: ToolDefinition;
  current_version: number; integration_id: string | null; updated_at: string;
}

export interface Integration {
  id: string; name: string; kind: "postgres" | "rest_api"; config: Record<string, any>; status: string;
  has_credentials: boolean; credential_hint: string; updated_at: string;
}

export interface WorkflowSummary { id: string; name: string; description: string; agent_id: string | null; revision: number; updated_at: string }
export interface WorkflowIssue { node_id: string | null; severity: "error" | "warning"; message: string }
export interface WorkflowDetail extends WorkflowSummary { graph: WorkflowGraph; issues: WorkflowIssue[] }

export interface KnowledgeBase { id: string; name: string; description: string; embedding_model: string; created_at: string }
export interface KnowledgeDocument {
  id: string; knowledge_base_id: string; title: string; source_type: string; source_uri: string | null;
  status: "pending" | "processing" | "ready" | "failed"; error: string | null; size_bytes: number; chunk_count: number; created_at: string;
}

export interface PhoneNumber {
  id: string; e164: string; provider: string; purpose: "test" | "production"; status: string; agent_id: string | null;
  provider_ref: Record<string, any>; created_at: string;
}

export interface ToolCallResult {
  status: "succeeded" | "failed" | "rejected" | "confirmation_required"; tool: string; arguments: Record<string, any>;
  data: Record<string, any> | null; error: string | null; error_code: string | null; action: Record<string, any> | null;
  latency_ms: number;
}

export interface TurnResult {
  replies: string[]; language: string | null; dialect: string | null; dialect_confidence: number;
  dialect_scores: Record<string, number>; code_switching: boolean; intent: string | null; tool_calls: ToolCallResult[];
  actions: Record<string, any>[]; workflow: { current: string | null; status: string; path: string[]; variables: Record<string, any> } | null;
  events: Record<string, any>[]; latency_ms: Record<string, number>; ended: boolean; transferred: boolean;
  normalized_text: string | null;
}

export interface AudioClip { mime_type?: string; audio_base64?: string; latency_ms?: number; error?: string }

export interface TestSession {
  session_id: string; agent_version: { id: string; number: number; kind: string }; mode: "agent" | "workflow";
  result: TurnResult; audio: AudioClip[];
}

export interface CallSummary {
  id: string; agent_id: string; agent_version_id: string; channel: string; direction: string; is_test: boolean;
  from_number: string | null; to_number: string | null; status: string; started_at: string; ended_at: string | null;
  duration_seconds: number | null; language: string | null; dialect: string | null; intent: string | null;
  outcome: string | null; transferred_to: string | null; error: string | null; metrics: Record<string, any>;
}

export interface CallDetail {
  call: CallSummary;
  agent_version: { id: string; version_number: number; kind: string } | null;
  messages: { seq: number; role: string; content: string; original_text: string | null; normalized_text: string | null;
    language: string | null; dialect: string | null; metadata: Record<string, any>; created_at: string }[];
  transcripts: unknown[];
  has_recording?: boolean;
  tool_executions: { id: string; tool_name: string; category: string; source: string; arguments: Record<string, any>;
    result: Record<string, any> | null; status: string; error: string | null; latency_ms: number | null;
    requires_confirmation: boolean; confirmed: boolean; created_at: string }[];
  events: { type: string; payload: Record<string, any>; latency_ms: number | null; created_at: string }[];
  workflow: { status: string; current_node: string | null; path: string[]; variables: Record<string, any> } | null;
}

export interface Analytics {
  period_days: number; calls: number; answered_calls: number; completed_tasks: number; transferred_calls: number;
  failed_tasks: number; avg_duration_seconds: number; avg_response_latency_ms: number; customer_satisfaction: number | null;
  languages: { key: string; count: number }[]; dialects: { key: string; count: number }[];
  top_intents: { key: string; count: number }[]; outcomes: { key: string; count: number }[];
  tool_failures: { tool: string; count: number }[]; calls_per_day: { day: string; count: number }[];
}
