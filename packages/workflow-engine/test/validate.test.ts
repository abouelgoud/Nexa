import { describe, expect, it } from "vitest";

import { NODE_SPECS, producedVariables, referencedVariables, validateWorkflow } from "../src/index";

const node = (id: string, type: any, config: Record<string, unknown> = {}) => ({ id, type, label: id, config, position: { x: 0, y: 0 } });
const edge = (source: string, target: string, handle = "default", condition: string | null = null) =>
  ({ id: `${source}-${target}-${handle}`, source, target, handle, condition, label: "" });

describe("validateWorkflow", () => {
  it("accepts a minimal valid graph", () => {
    const g = { nodes: [node("start", "start"), node("bye", "end", { text: "bye" })], edges: [edge("start", "bye")] };
    expect(validateWorkflow(g).filter((i) => i.severity === "error")).toEqual([]);
  });

  it("reports business-language problems", () => {
    const g = {
      nodes: [node("start", "start"), node("c", "confirm", { text: "" }), node("t", "tool"), node("orphan", "say", { text: "hi" })],
      edges: [edge("start", "c"), edge("c", "t", "yes")],
    };
    const msgs = validateWorkflow(g, new Set(["book"])).map((i) => i.message);
    expect(msgs).toContain('"c" is missing the confirmation question.');
    expect(msgs).toContain('"c" needs both a "yes" and a "no" path.');
    expect(msgs).toContain('"t" does not have an action selected.');
    expect(msgs).toContain('Step "orphan" can never be reached.');
  });

  it("flags actions that are not enabled", () => {
    const g = { nodes: [node("start", "start"), node("t", "tool", { tool: "delete_everything" }), node("e", "end")],
      edges: [edge("start", "t"), edge("t", "e", "success"), edge("t", "e", "error")] };
    expect(validateWorkflow(g, new Set(["book"]))[0].message).toContain("not enabled");
  });

  it("requires exactly one start", () => {
    expect(validateWorkflow({ nodes: [node("x", "say", { text: "a" })], edges: [] })[0].message).toContain("exactly one Start");
  });
});

describe("variables", () => {
  it("finds references and outputs", () => {
    expect(referencedVariables({ text: "موعدك {{slot.label}} مع {{doctor.label}}" }).sort()).toEqual(["doctor", "slot"]);
    const g = { nodes: [node("a", "collect", { variable: "phone" }), node("b", "tool", { result_variable: "slots" })], edges: [] };
    expect(producedVariables(g)).toEqual(expect.arrayContaining(["phone", "slots", "caller_number"]));
  });

  it("covers every node type", () => {
    expect(Object.keys(NODE_SPECS)).toHaveLength(11);
  });
});
