/**
 * Zod mirror of the Python `AgentDefinition` (apps/api/nexa/schemas/agent_definition.py).
 * The JSON Schemas exported from Pydantic live next to this file and a test checks that
 * enums/fields stay in sync.
 */
import { z } from "zod";

export const LANGUAGES = ["ar", "en"] as const;
export const ARABIC_DIALECTS = [
  "sa", "gulf", "ae", "kw", "qa", "bh", "om", "iq", "levant", "eg", "sd", "ye", "ly", "tn", "dz", "ma", "ar",
] as const;
export const CAPABILITIES = [
  "answer_questions", "book_appointment", "cancel_appointment", "reschedule_appointment", "get_appointment",
  "transfer_call", "take_order", "check_order_status", "make_reservation", "capture_lead", "collect_information",
] as const;
export const TONES = ["professional", "friendly", "warm", "formal", "energetic"] as const;
export const VERBOSITY = ["concise", "balanced", "detailed"] as const;
export const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;

export const DIALECT_LABELS: Record<(typeof ARABIC_DIALECTS)[number], { en: string; ar: string }> = {
  sa: { en: "Saudi / Najdi", ar: "سعودي / نجدي" },
  gulf: { en: "Gulf", ar: "خليجي" },
  ae: { en: "Emirati", ar: "إماراتي" },
  kw: { en: "Kuwaiti", ar: "كويتي" },
  qa: { en: "Qatari", ar: "قطري" },
  bh: { en: "Bahraini", ar: "بحريني" },
  om: { en: "Omani", ar: "عماني" },
  iq: { en: "Iraqi", ar: "عراقي" },
  levant: { en: "Levantine", ar: "شامي" },
  eg: { en: "Egyptian", ar: "مصري" },
  sd: { en: "Sudanese", ar: "سوداني" },
  ye: { en: "Yemeni", ar: "يمني" },
  ly: { en: "Libyan", ar: "ليبي" },
  tn: { en: "Tunisian", ar: "تونسي" },
  dz: { en: "Algerian", ar: "جزائري" },
  ma: { en: "Moroccan / Darija", ar: "مغربي / دارجة" },
  ar: { en: "Modern Standard Arabic", ar: "العربية الفصحى" },
};

const hhmm = z.string().regex(/^\d{2}:\d{2}$/, "Use HH:MM");

export const languageBehaviorSchema = z.strictObject({
  mode: z.enum(["match_caller", "fixed"]).default("match_caller"),
  primary_language: z.enum(LANGUAGES).default("ar"),
  code_switching: z.boolean().default(true),
  response_dialect: z.union([z.enum(ARABIC_DIALECTS), z.literal("match_caller")]).default("match_caller"),
  vocabulary: z.array(z.string()).max(200).default([]),
});

export const VOICE_PROVIDERS = ["local", "piper", "neural", "elevenlabs", "azure"] as const;

export const voiceSchema = z.strictObject({
  provider: z.enum(VOICE_PROVIDERS).default("local"),
  voice_id: z.string().min(1, "Choose a voice").default("default-ar"),
  english_voice_id: z.string().nullable().default("default-en"),
  speed: z.number().min(0.5).max(2).default(1),
  match_caller_dialect: z.boolean().default(false),
  gender: z.enum(["female", "male"]).default("male"),
  thinking_fillers: z.boolean().default(true),
});

export const personalitySchema = z.strictObject({
  tone: z.enum(TONES).default("professional"),
  verbosity: z.enum(VERBOSITY).default("concise"),
  custom_instructions: z.string().max(4000).default(""),
});

export const policiesSchema = z.strictObject({
  require_confirmation_for_booking: z.boolean().default(true),
  never_invent_information: z.boolean().default(true),
  human_handoff_enabled: z.boolean().default(true),
});

export const operatingDaySchema = z.strictObject({ day: z.enum(DAYS), open: hhmm, close: hhmm });

export const transferTargetSchema = z.strictObject({
  key: z.string().regex(/^[a-z0-9_]{1,50}$/, "Use lowercase letters, numbers and _"),
  label: z.string().min(1),
  phone_number: z.string().regex(/^\+?[0-9]{3,20}$/, "Enter a phone number"),
  only_during_business_hours: z.boolean().default(false),
});

export const handoffSchema = z.strictObject({
  enabled: z.boolean().default(true),
  default_target: z.string().nullable().default(null),
  targets: z.array(transferTargetSchema).default([]),
  on_explicit_request: z.boolean().default(true),
  on_low_confidence: z.boolean().default(true),
  confidence_threshold: z.number().min(0).max(1).default(0.5),
  on_task_failure: z.boolean().default(true),
  after_hours_message: z.string().default(""),
});

export const privacySchema = z.strictObject({
  record_calls: z.boolean().default(false),
  store_audio: z.boolean().default(false),
  store_transcript: z.boolean().default(true),
  retention_days: z.number().int().min(1).max(3650).default(30),
  consent_required: z.boolean().default(false),
  consent_message: z.string().default(""),
});

export const generalSchema = z.strictObject({
  business_name: z.string().default(""),
  industry: z.string().default("general"),
  greeting: z.string().default(""),
  greeting_en: z.string().default(""),
  timezone: z.string().default("Asia/Riyadh"),
  operating_hours: z.array(operatingDaySchema).default([]),
});

export const agentDefinitionSchema = z
  .strictObject({
    schema_version: z.literal(1).default(1),
    name: z.string().min(1, "Give the agent a name").max(200),
    description: z.string().max(2000).default(""),
    general: generalSchema.default(generalSchema.parse({})),
    languages: z.array(z.enum(LANGUAGES)).min(1, "Choose at least one language").default(["ar", "en"]),
    arabic_dialects: z.array(z.enum(ARABIC_DIALECTS)).default([...ARABIC_DIALECTS]),
    language_behavior: languageBehaviorSchema.default(languageBehaviorSchema.parse({})),
    voice: voiceSchema.default(voiceSchema.parse({})),
    personality: personalitySchema.default(personalitySchema.parse({})),
    capabilities: z.array(z.enum(CAPABILITIES)).default([]),
    knowledge_base_ids: z.array(z.uuid()).default([]),
    tool_ids: z.array(z.uuid()).default([]),
    workflow_id: z.uuid().nullable().default(null),
    execution_mode: z.enum(["agent", "workflow"]).default("agent"),
    policies: policiesSchema.default(policiesSchema.parse({})),
    handoff: handoffSchema.default(handoffSchema.parse({})),
    privacy: privacySchema.default(privacySchema.parse({})),
  })
  .superRefine((d, ctx) => {
    const keys = d.handoff.targets.map((t) => t.key);
    if (new Set(keys).size !== keys.length) {
      ctx.addIssue({ code: "custom", path: ["handoff", "targets"], message: "Transfer destinations must have unique keys" });
    }
    if (d.handoff.default_target && !keys.includes(d.handoff.default_target)) {
      ctx.addIssue({ code: "custom", path: ["handoff", "default_target"],
        message: `Default transfer destination '${d.handoff.default_target}' does not exist` });
    }
    if (d.execution_mode === "workflow" && !d.workflow_id) {
      ctx.addIssue({ code: "custom", path: ["workflow_id"], message: "Workflow mode requires a workflow to be selected" });
    }
  });

export type AgentDefinition = z.infer<typeof agentDefinitionSchema>;
export type AgentDefinitionInput = z.input<typeof agentDefinitionSchema>;

// ---------------------------------------------------------------------------------------------
// Tools

export const TOOL_CATEGORIES = [
  "database", "rest_api", "calendar", "crm", "sms", "email", "whatsapp", "voice", "workflow", "human_handoff", "knowledge",
] as const;
export const TOOL_EXECUTORS = ["database", "rest_api", "transfer_call", "end_call", "knowledge_search"] as const;
export const DB_OPERATIONS = ["get_record", "search_records", "create_record", "update_record", "delete_record"] as const;
export const FILTER_OPS = ["eq", "ne", "lt", "lte", "gt", "gte", "like", "ilike", "in", "is_null", "not_null"] as const;
export const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

const ident = z.string().regex(/^[A-Za-z_][A-Za-z0-9_]{0,62}$/, "Use letters, numbers and _ only");

export const dbFilterSchema = z.strictObject({
  field: ident,
  op: z.enum(FILTER_OPS).default("eq"),
  arg: z.string().nullable().default(null),
  value: z.any().optional(),
  optional: z.boolean().default(false),
});

export const databaseToolConfigSchema = z.strictObject({
  integration_id: z.uuid(),
  operation: z.enum(DB_OPERATIONS),
  db_schema: ident.default("public"),
  table: ident,
  filters: z.array(dbFilterSchema).default([]),
  return_fields: z.array(ident).default([]),
  values: z.record(z.string(), z.any()).default({}),
  order_by: z.array(z.string()).default([]),
  limit: z.number().int().min(1).max(100).default(10),
});

export const restToolConfigSchema = z.strictObject({
  integration_id: z.uuid(),
  method: z.enum(HTTP_METHODS).default("GET"),
  path: z.string().default("/"),
  query: z.record(z.string(), z.any()).default({}),
  headers: z.record(z.string(), z.string()).default({}),
  body: z.record(z.string(), z.any()).nullable().default(null),
  response_mapping: z.record(z.string(), z.string()).default({}),
  timeout_seconds: z.number().positive().max(60).default(10),
});

export const toolDefinitionSchema = z.strictObject({
  name: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/, "Use lowercase letters, numbers and _ (e.g. book_appointment)"),
  display_name: z.string().default(""),
  description: z.string().min(3).max(1000),
  category: z.enum(TOOL_CATEGORIES),
  executor: z.enum(TOOL_EXECUTORS),
  input_schema: z.record(z.string(), z.any()).default({ type: "object", properties: {} }),
  requires_confirmation: z.boolean().default(false),
  confirmation_template: z.string().default(""),
  config: z.record(z.string(), z.any()).default({}),
});
export type ToolDefinition = z.infer<typeof toolDefinitionSchema>;

// ---------------------------------------------------------------------------------------------
// Workflows

export const NODE_TYPES = [
  "start", "say", "ask", "collect", "condition", "tool", "knowledge_search", "transfer", "wait", "confirm", "end",
] as const;
export type NodeType = (typeof NODE_TYPES)[number];

export const workflowNodeSchema = z.strictObject({
  id: z.string().regex(/^[A-Za-z0-9_-]{1,100}$/),
  type: z.enum(NODE_TYPES),
  label: z.string().default(""),
  config: z.record(z.string(), z.any()).default({}),
  position: z.object({ x: z.number(), y: z.number() }).default({ x: 0, y: 0 }),
});
export const workflowEdgeSchema = z.strictObject({
  id: z.string().regex(/^[A-Za-z0-9_-]{1,100}$/),
  source: z.string(),
  target: z.string(),
  handle: z.string().default("default"),
  condition: z.string().nullable().default(null),
  label: z.string().default(""),
});
export const workflowGraphSchema = z.strictObject({
  nodes: z.array(workflowNodeSchema),
  edges: z.array(workflowEdgeSchema).default([]),
});
export type WorkflowNode = z.infer<typeof workflowNodeSchema>;
export type WorkflowEdge = z.infer<typeof workflowEdgeSchema>;
export type WorkflowGraph = z.infer<typeof workflowGraphSchema>;

/** Turn Zod issues into business-language messages (same style as the API). */
export function friendlyIssues(error: z.ZodError): { field: string; message: string }[] {
  return error.issues.map((i) => {
    const field = i.path.join(" → ") || "value";
    return { field, message: `${field.replace(/_/g, " ")}: ${i.message}` };
  });
}
