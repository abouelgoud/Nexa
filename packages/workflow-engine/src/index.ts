/**
 * Workflow node catalog and client-side validation for the visual builder.
 * The authoritative runtime is the Python WorkflowEngine (apps/api/nexa/workflow/engine.py);
 * this package gives instant feedback while editing and mirrors `validate_workflow`.
 */
import type { NodeType, WorkflowGraph } from "@nexa/agent-schema";

export interface NodeSpec {
  type: NodeType;
  label: { en: string; ar: string };
  description: string;
  /** Fixed outgoing branches. `null` = free-form branches (intents / conditions). */
  handles: string[] | null;
  defaultConfig: Record<string, unknown>;
  color: string;
}

export const NODE_SPECS: Record<NodeType, NodeSpec> = {
  start: { type: "start", label: { en: "Start", ar: "البداية" }, description: "Where every call begins.",
    handles: ["default"], defaultConfig: {}, color: "#16a34a" },
  say: { type: "say", label: { en: "Say", ar: "قول" }, description: "The agent says a sentence.",
    handles: ["default"], defaultConfig: { text: "", text_en: "" }, color: "#2563eb" },
  ask: { type: "ask", label: { en: "Ask", ar: "سؤال" },
    description: "Ask an open question and understand the caller's intent.", handles: null,
    defaultConfig: { question: "", question_en: "", variable: "request", intents: {} }, color: "#7c3aed" },
  collect: { type: "collect", label: { en: "Collect information", ar: "جمع معلومة" },
    description: "Collect one piece of information (name, phone, date, choice...).", handles: ["default", "failed"],
    defaultConfig: { variable: "", type: "text", prompt: "", prompt_en: "", max_attempts: 2 }, color: "#9333ea" },
  condition: { type: "condition", label: { en: "Condition", ar: "شرط" },
    description: "Choose a path based on collected information.", handles: null, defaultConfig: {}, color: "#ca8a04" },
  tool: { type: "tool", label: { en: "Action", ar: "إجراء" },
    description: "Run an action such as finding slots or booking an appointment.", handles: ["success", "error"],
    defaultConfig: { tool: "", arguments: {}, result_variable: "" }, color: "#ea580c" },
  knowledge_search: { type: "knowledge_search", label: { en: "Knowledge search", ar: "بحث في المعرفة" },
    description: "Answer from your business knowledge. Never invents answers.", handles: ["found", "not_found"],
    defaultConfig: { query: "{{last_input}}", result_variable: "knowledge" }, color: "#0891b2" },
  transfer: { type: "transfer", label: { en: "Transfer", ar: "تحويل" },
    description: "Transfer the caller to a human.", handles: ["default"],
    defaultConfig: { target: "", text: "لحظة من فضلك، بحولك على أحد الموظفين.", text_en: "One moment, transferring you." },
    color: "#dc2626" },
  wait: { type: "wait", label: { en: "Wait", ar: "انتظار" }, description: "Pause briefly.",
    handles: ["default"], defaultConfig: { seconds: 1 }, color: "#64748b" },
  confirm: { type: "confirm", label: { en: "Confirm", ar: "تأكيد" },
    description: "Ask a yes/no question before doing something important.", handles: ["yes", "no"],
    defaultConfig: { text: "", text_en: "" }, color: "#0d9488" },
  end: { type: "end", label: { en: "End call", ar: "إنهاء المكالمة" }, description: "Say goodbye and hang up.",
    handles: [], defaultConfig: { text: "", text_en: "" }, color: "#475569" },
};

export interface Issue {
  nodeId: string | null;
  severity: "error" | "warning";
  message: string;
}

/** Mirrors nexa.schemas.workflow.validate_workflow (business-language messages). */
export function validateWorkflow(graph: WorkflowGraph, toolNames?: Set<string>): Issue[] {
  const issues: Issue[] = [];
  const ids = graph.nodes.map((n) => n.id);
  if (new Set(ids).size !== ids.length) issues.push({ nodeId: null, severity: "error", message: "Each step must have a unique id." });
  const starts = graph.nodes.filter((n) => n.type === "start");
  if (starts.length !== 1) {
    issues.push({ nodeId: null, severity: "error", message: "The workflow must have exactly one Start step." });
    return issues;
  }
  for (const e of graph.edges) {
    if (!ids.includes(e.source) || !ids.includes(e.target)) {
      issues.push({ nodeId: null, severity: "error", message: `Connection ${e.id} points to a step that does not exist.` });
    }
  }
  const out = (id: string) => graph.edges.filter((e) => e.source === id);
  const seen = new Set<string>();
  const stack = [starts[0].id];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    out(id).forEach((e) => stack.push(e.target));
  }
  for (const n of graph.nodes) {
    const name = n.label || n.id;
    const edges = out(n.id);
    const c = n.config as Record<string, unknown>;
    if (!seen.has(n.id)) issues.push({ nodeId: n.id, severity: "warning", message: `Step "${name}" can never be reached.` });
    if (n.type !== "end" && n.type !== "transfer" && edges.length === 0) {
      issues.push({ nodeId: n.id, severity: "error", message: `Step "${name}" has no next step.` });
    }
    const allowed = NODE_SPECS[n.type].handles;
    if (allowed !== null) {
      const ok = new Set([...allowed, "default"]);
      for (const e of edges) {
        if (!ok.has(e.handle)) issues.push({ nodeId: n.id, severity: "error", message: `Step "${name}" has an unknown branch "${e.handle}".` });
      }
    }
    if (n.type === "say" && !c.text && !c.text_en) issues.push({ nodeId: n.id, severity: "error", message: `"${name}" has nothing to say.` });
    if (n.type === "ask" && !c.question) issues.push({ nodeId: n.id, severity: "error", message: `"${name}" is missing its question.` });
    if (n.type === "collect" && !c.variable) {
      issues.push({ nodeId: n.id, severity: "error", message: `"${name}" does not say which information to collect.` });
    }
    if (n.type === "confirm") {
      if (!c.text) issues.push({ nodeId: n.id, severity: "error", message: `"${name}" is missing the confirmation question.` });
      const hs = new Set(edges.map((e) => e.handle));
      if (!hs.has("yes") || !hs.has("no")) issues.push({ nodeId: n.id, severity: "error", message: `"${name}" needs both a "yes" and a "no" path.` });
    }
    if (n.type === "tool") {
      if (!c.tool) issues.push({ nodeId: n.id, severity: "error", message: `"${name}" does not have an action selected.` });
      else if (toolNames && !toolNames.has(String(c.tool))) {
        issues.push({ nodeId: n.id, severity: "error", message: `"${name}" uses the action "${c.tool}" which is not enabled for this agent.` });
      }
    }
    if (n.type === "condition" && !edges.some((e) => !e.condition || e.condition === "else" || e.handle === "else")) {
      issues.push({ nodeId: n.id, severity: "warning", message: `"${name}" has no "otherwise" path.` });
    }
  }
  return issues;
}

/** Variables referenced as {{var.path}} in a node's texts/arguments (for the variable picker). */
export function referencedVariables(config: Record<string, unknown>): string[] {
  const found = new Set<string>();
  const walk = (v: unknown) => {
    if (typeof v === "string") for (const m of v.matchAll(/\{\{\s*([A-Za-z0-9_.]+)/g)) found.add(m[1].split(".")[0]);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  walk(config);
  return [...found];
}

/** Variables produced by nodes (collect/ask/tool/knowledge) - offered in pickers downstream. */
export function producedVariables(graph: WorkflowGraph): string[] {
  const vars = new Set<string>(["greeting", "business_name", "caller_number", "today", "last_input", "intent"]);
  for (const n of graph.nodes) {
    const c = n.config as Record<string, string>;
    if (c.variable) vars.add(c.variable);
    if (c.result_variable) vars.add(c.result_variable);
  }
  return [...vars];
}

let counter = 0;
export function newNodeId(type: NodeType): string {
  counter += 1;
  return `${type}_${Date.now().toString(36)}${counter}`;
}
