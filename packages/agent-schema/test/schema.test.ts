import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  ARABIC_DIALECTS, CAPABILITIES, DB_OPERATIONS, NODE_TYPES, TOOL_CATEGORIES, TOOL_EXECUTORS,
  agentDefinitionSchema, toolDefinitionSchema, workflowGraphSchema,
} from "../src/index";

const here = dirname(fileURLToPath(import.meta.url));
const load = (name: string) => JSON.parse(readFileSync(join(here, "..", name), "utf8"));
const agentJson = load("agent-definition.schema.json");
const toolJson = load("tool-definition.schema.json");
const wfJson = load("workflow-graph.schema.json");

describe("agent definition", () => {
  it("accepts the product spec example", () => {
    const parsed = agentDefinitionSchema.parse({
      name: "ABC Receptionist",
      description: "AI receptionist for ABC Clinic",
      languages: ["ar", "en"],
      arabic_dialects: ["sa", "gulf", "eg", "levant", "iq", "ye", "sd", "ma", "dz", "tn", "ly", "ar"],
      language_behavior: { mode: "match_caller", code_switching: true },
      voice: { provider: "local", voice_id: "default-ar" },
      personality: { tone: "professional", verbosity: "concise" },
      capabilities: ["answer_questions", "book_appointment", "cancel_appointment", "reschedule_appointment", "transfer_call"],
      knowledge_base_ids: [],
      tool_ids: [],
      workflow_id: "6f1c9a8e-1d2b-4c3d-9e8f-0a1b2c3d4e5f",
      policies: { require_confirmation_for_booking: true, never_invent_information: true, human_handoff_enabled: true },
    });
    expect(parsed.privacy.store_audio).toBe(false);
    expect(parsed.execution_mode).toBe("agent");
  });

  it("rejects unknown fields and bad dialects", () => {
    expect(agentDefinitionSchema.safeParse({ name: "x", api_key: "y" }).success).toBe(false);
    expect(agentDefinitionSchema.safeParse({ name: "x", arabic_dialects: ["xx"] }).success).toBe(false);
  });

  it("requires a workflow in workflow mode", () => {
    const r = agentDefinitionSchema.safeParse({ name: "x", execution_mode: "workflow" });
    expect(r.success).toBe(false);
  });

  it("has the same fields and enums as the Pydantic JSON schema", () => {
    const pyFields = Object.keys(agentJson.properties).sort();
    expect(Object.keys(agentDefinitionSchema.shape).sort()).toEqual(pyFields);
    expect([...ARABIC_DIALECTS].sort()).toEqual([...agentJson.$defs.ArabicDialect.enum].sort());
    expect([...CAPABILITIES].sort()).toEqual([...agentJson.$defs.Capability.enum].sort());
  });
});

describe("tool definition", () => {
  it("matches the Pydantic enums", () => {
    expect([...TOOL_CATEGORIES].sort()).toEqual([...toolJson.$defs.ToolCategory.enum].sort());
    expect([...TOOL_EXECUTORS].sort()).toEqual([...toolJson.properties.executor.enum].sort());
    expect(DB_OPERATIONS.length).toBe(5);
  });

  it("validates names", () => {
    const base = { description: "Book", category: "calendar", executor: "database" } as const;
    expect(toolDefinitionSchema.safeParse({ ...base, name: "book_appointment" }).success).toBe(true);
    expect(toolDefinitionSchema.safeParse({ ...base, name: "Book Appointment" }).success).toBe(false);
  });
});

describe("workflow graph", () => {
  it("matches node types", () => {
    const pyTypes = wfJson.$defs.WorkflowNodeDef.properties.type.enum;
    expect([...NODE_TYPES].sort()).toEqual([...pyTypes].sort());
    expect(workflowGraphSchema.safeParse({ nodes: [{ id: "start", type: "start" }] }).success).toBe(true);
  });
});
