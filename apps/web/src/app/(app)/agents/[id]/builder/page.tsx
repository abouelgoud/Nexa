"use client";

import "@xyflow/react/dist/style.css";

import { NODE_TYPES, type NodeType, type WorkflowGraph } from "@nexa/agent-schema";
import type { WorkflowSummary } from "@nexa/shared-types";
import { Alert, Badge, Button, Card, CardContent, Input, Label, Select, Spinner, Textarea } from "@nexa/ui";
import { NODE_SPECS, newNodeId, producedVariables, validateWorkflow } from "@nexa/workflow-engine";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Background, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, addEdge, useEdgesState, useNodesState,
  type Connection, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { Plus, Save, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { post, put } from "@/lib/api";
import { useAgent, useSaveAgentConfig, useTools, useWorkflow } from "@/lib/queries";

type NodeData = { type: NodeType; label: string; config: Record<string, any>; issues?: string[] };
type FlowNode = Node<NodeData>;

function handlesFor(node: FlowNode, edges: Edge[]): string[] {
  const spec = NODE_SPECS[node.data.type];
  if (spec.handles) return spec.handles;
  const existing = edges.filter((e) => e.source === node.id).map((e) => e.sourceHandle ?? "default");
  if (node.data.type === "ask") return [...new Set([...Object.keys(node.data.config.intents ?? {}), "default", ...existing])];
  return [...new Set([...existing, "__new__"])];
}

function summary(d: NodeData): string {
  const c = d.config;
  switch (d.type) {
    case "say": case "end": case "confirm": case "transfer": return c.text ?? "";
    case "ask": return c.question ?? "";
    case "collect": return `${c.variable ?? "?"} (${c.type ?? "text"}) - ${c.prompt ?? ""}`;
    case "tool": return c.tool ? `Run: ${c.tool}` : "No action selected";
    case "knowledge_search": return `Search: ${c.query ?? ""}`;
    case "wait": return `${c.seconds ?? 1}s`;
    default: return "";
  }
}

function StepNode({ data, id, selected }: NodeProps<FlowNode>) {
  const spec = NODE_SPECS[data.type];
  const handles: string[] = (data as any).handles ?? [];
  return (
    <div className={`min-w-[200px] max-w-[260px] rounded-lg border bg-card text-xs shadow-sm ${selected ? "ring-2 ring-primary" : ""}`}
      style={{ borderTop: `4px solid ${spec.color}` }}>
      {data.type !== "start" && <Handle type="target" position={Position.Top} />}
      <div className="p-2">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">{data.label || id}</span>
          <span className="text-[10px] uppercase text-muted-foreground">{spec.label.en}</span>
        </div>
        <div dir="auto" className="mt-1 line-clamp-2 text-muted-foreground">{summary(data)}</div>
        {data.issues && data.issues.length > 0 && <div className="mt-1 text-[10px] text-red-600">{data.issues[0]}</div>}
      </div>
      {handles.length > 0 && (
        <div className="flex justify-around border-t px-1 pb-1 pt-1 text-[9px] text-muted-foreground">
          {handles.map((h) => <span key={h}>{h === "__new__" ? "+" : h}</span>)}
        </div>
      )}
      {handles.map((h, i) => (
        <Handle key={h} type="source" id={h} position={Position.Bottom}
          style={{ left: `${((i + 1) / (handles.length + 1)) * 100}%`, background: h === "__new__" ? "#94a3b8" : spec.color }} />
      ))}
    </div>
  );
}

const nodeTypes = { step: StepNode };

function toFlow(graph: WorkflowGraph): { nodes: FlowNode[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((n) => ({ id: n.id, type: "step", position: n.position, data: { type: n.type, label: n.label, config: n.config } })),
    edges: graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.handle,
      label: e.handle !== "default" ? e.handle : undefined, data: { condition: e.condition } })),
  };
}

function toGraph(nodes: FlowNode[], edges: Edge[]): WorkflowGraph {
  return {
    nodes: nodes.map((n) => ({ id: n.id, type: n.data.type, label: n.data.label, config: n.data.config,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, handle: e.sourceHandle ?? "default",
      condition: (e.data as any)?.condition ?? null, label: typeof e.label === "string" ? e.label : "" })),
  };
}

function TextPair({ config, set, field, label }: { config: any; set: (k: string, v: any) => void; field: string; label: string }) {
  return (
    <>
      <div className="space-y-1"><Label>{label} (Arabic)</Label><Textarea dir="auto" rows={2} value={config[field] ?? ""} onChange={(e) => set(field, e.target.value)} /></div>
      <div className="space-y-1"><Label>{label} (English)</Label><Textarea dir="auto" rows={2} value={config[`${field}_en`] ?? ""} onChange={(e) => set(`${field}_en`, e.target.value)} /></div>
    </>
  );
}

function NodeEditor({ node, edges, variables, toolNames, onChange, onEdgeChange, onDelete }: {
  node: FlowNode; edges: Edge[]; variables: string[]; toolNames: string[];
  onChange: (data: Partial<NodeData>) => void; onEdgeChange: (id: string, patch: Partial<Edge>) => void; onDelete: () => void;
}) {
  const c = node.data.config;
  const set = (k: string, v: any) => onChange({ config: { ...c, [k]: v } });
  const out = edges.filter((e) => e.source === node.id);
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center justify-between"><Badge>{NODE_SPECS[node.data.type].label.en}</Badge>
        {node.data.type !== "start" && <Button size="icon" variant="ghost" onClick={onDelete}><Trash2 className="h-4 w-4" /></Button>}</div>
      <p className="text-xs text-muted-foreground">{NODE_SPECS[node.data.type].description}</p>
      <div className="space-y-1"><Label>Step name</Label><Input value={node.data.label} onChange={(e) => onChange({ label: e.target.value })} /></div>
      {["say", "end", "confirm", "transfer", "wait"].includes(node.data.type) && <TextPair config={c} set={set} field="text" label={node.data.type === "confirm" ? "Question" : "Text"} />}
      {node.data.type === "transfer" && <div className="space-y-1"><Label>Destination key</Label><Input value={c.target ?? ""} onChange={(e) => set("target", e.target.value)} placeholder="reception" /></div>}
      {node.data.type === "wait" && <div className="space-y-1"><Label>Seconds</Label><Input type="number" value={c.seconds ?? 1} onChange={(e) => set("seconds", Number(e.target.value))} /></div>}
      {node.data.type === "ask" && (<>
        <TextPair config={c} set={set} field="question" label="Question" />
        <div className="space-y-1"><Label>Save answer as</Label><Input value={c.variable ?? ""} onChange={(e) => set("variable", e.target.value)} /></div>
        <Label>Intents (each becomes a branch)</Label>
        {Object.entries<string[]>(c.intents ?? {}).map(([name, words]) => (
          <div key={name} className="space-y-1 rounded border p-2">
            <div className="flex justify-between"><span className="font-medium">{name}</span>
              <button className="text-xs text-destructive" onClick={() => { const n = { ...c.intents }; delete n[name]; set("intents", n); }}>remove</button></div>
            <Input dir="auto" value={words.join(", ")} placeholder="keywords, comma separated"
              onChange={(e) => set("intents", { ...c.intents, [name]: e.target.value.split(",").map((w) => w.trim()) })} />
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => { const name = window.prompt("Intent name (e.g. book)"); if (name) set("intents", { ...(c.intents ?? {}), [name]: [] }); }}>
          <Plus className="h-3.5 w-3.5" /> Add intent</Button>
      </>)}
      {node.data.type === "collect" && (<>
        <div className="space-y-1"><Label>Save as</Label><Input value={c.variable ?? ""} onChange={(e) => set("variable", e.target.value)} /></div>
        <div className="space-y-1"><Label>Kind of information</Label>
          <Select value={c.type ?? "text"} onChange={(e) => set("type", e.target.value)}>
            {["text", "phone", "date", "time", "number", "choice"].map((t) => <option key={t}>{t}</option>)}
          </Select></div>
        <TextPair config={c} set={set} field="prompt" label="Question" />
        {c.type === "choice" && (<>
          <div className="space-y-1"><Label>Options come from</Label>
            <Input value={c.options_from ?? ""} onChange={(e) => set("options_from", e.target.value)} placeholder="slots.records" /></div>
          <div className="space-y-1"><Label>Match on fields (comma separated)</Label>
            <Input value={(c.label_fields ?? []).join(", ")} onChange={(e) => set("label_fields", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></div>
          <div className="space-y-1"><Label>Value field</Label><Input value={c.value_field ?? "id"} onChange={(e) => set("value_field", e.target.value)} /></div>
        </>)}
        <div className="space-y-1"><Label>Fill automatically from</Label>
          <Select value={c.prefill_from ?? ""} onChange={(e) => set("prefill_from", e.target.value || undefined)}>
            <option value="">-</option>{variables.map((v) => <option key={v}>{v}</option>)}
          </Select></div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!c.optional} onChange={(e) => set("optional", e.target.checked)} /> Optional (caller may say no preference)</label>
      </>)}
      {node.data.type === "tool" && (<>
        <div className="space-y-1"><Label>Action</Label>
          <Select value={c.tool ?? ""} onChange={(e) => set("tool", e.target.value)}>
            <option value="">Choose…</option>{toolNames.map((t) => <option key={t}>{t}</option>)}
          </Select></div>
        <Label>Inputs</Label>
        {Object.entries<string>(c.arguments ?? {}).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2"><span className="w-24 truncate text-xs">{k}</span>
            <Input value={v} onChange={(e) => set("arguments", { ...c.arguments, [k]: e.target.value })} placeholder="{{variable}}" /></div>
        ))}
        <Button size="sm" variant="outline" onClick={() => { const k = window.prompt("Input name"); if (k) set("arguments", { ...(c.arguments ?? {}), [k]: "" }); }}>
          <Plus className="h-3.5 w-3.5" /> Add input</Button>
        <div className="space-y-1"><Label>Save result as</Label><Input value={c.result_variable ?? ""} onChange={(e) => set("result_variable", e.target.value)} /></div>
        <div className="space-y-1"><Label>Requires the yes from step</Label><Input value={c.confirmed_by ?? ""} onChange={(e) => set("confirmed_by", e.target.value || undefined)} placeholder="confirm step id" /></div>
      </>)}
      {node.data.type === "knowledge_search" && (<>
        <div className="space-y-1"><Label>Question to search</Label><Input value={c.query ?? ""} onChange={(e) => set("query", e.target.value)} /></div>
        <div className="space-y-1"><Label>Save result as</Label><Input value={c.result_variable ?? ""} onChange={(e) => set("result_variable", e.target.value)} /></div>
      </>)}
      {node.data.type === "condition" && (<>
        <Label>Branches (first true condition wins; empty = otherwise)</Label>
        {out.map((e) => (
          <div key={e.id} className="space-y-1 rounded border p-2">
            <Input value={e.sourceHandle ?? ""} onChange={(ev) => onEdgeChange(e.id, { sourceHandle: ev.target.value, label: ev.target.value })} placeholder="branch name" />
            <Input value={(e.data as any)?.condition ?? ""} placeholder='e.g. not empty(slots.records)'
              onChange={(ev) => onEdgeChange(e.id, { data: { ...(e.data ?? {}), condition: ev.target.value || null } })} />
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Drag from the + handle to add a branch.</p>
      </>)}
      <div className="rounded bg-muted/50 p-2 text-xs text-muted-foreground">
        Available variables: {variables.map((v) => <code key={v} className="me-1">{`{{${v}}}`}</code>)}
      </div>
    </div>
  );
}

function Builder({ workflowId }: { workflowId: string }) {
  const wf = useWorkflow(workflowId);
  if (wf.isLoading || !wf.data) return <Spinner />;
  // Remount the canvas whenever a new revision is loaded from the server.
  return <Canvas key={`${wf.data.id}:${wf.data.revision}`} workflowId={workflowId} initial={wf.data.graph} />;
}

function Canvas({ workflowId, initial }: { workflowId: string; initial: WorkflowGraph }) {
  const { id: agentId } = useParams<{ id: string }>();
  const tools = useTools();
  const agent = useAgent(agentId);
  const qc = useQueryClient();
  const [flow] = useState(() => toFlow(initial));
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(flow.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(flow.edges);
  const [selected, setSelected] = useState<string | null>(null);
  // Open zoomed on the beginning of the conversation instead of shrinking large flows to fit.
  const [initialFocus] = useState(() => {
    const start = flow.nodes.find((n) => n.data.type === "start");
    if (!start) return undefined;
    return flow.nodes.filter((n) => Math.abs(n.position.y - start.position.y) < 700).map((n) => ({ id: n.id }));
  });

  const enabledTools = useMemo(() => {
    const ids = new Set(agent.data?.draft_config.tool_ids ?? []);
    return [...(tools.data ?? []).filter((t) => ids.has(t.id)).map((t) => t.name), "transfer_call", "end_call", "search_knowledge"];
  }, [tools.data, agent.data]);
  const graph = useMemo(() => toGraph(nodes, edges), [nodes, edges]);
  const issues = useMemo(() => validateWorkflow(graph, new Set(enabledTools)), [graph, enabledTools]);
  const variables = useMemo(() => producedVariables(graph), [graph]);
  const displayNodes = useMemo(() => nodes.map((n) => ({ ...n, data: { ...n.data, handles: handlesFor(n, edges),
    issues: issues.filter((i) => i.nodeId === n.id && i.severity === "error").map((i) => i.message) } })), [nodes, edges, issues]);

  const onConnect = useCallback((c: Connection) => {
    const handle = c.sourceHandle === "__new__" ? `branch_${Math.random().toString(36).slice(2, 6)}` : c.sourceHandle ?? "default";
    setEdges((es) => addEdge({ ...c, sourceHandle: handle, id: `${c.source}__${handle}__${c.target}`,
      label: handle !== "default" ? handle : undefined, data: { condition: null } }, es.filter((e) => !(e.source === c.source && e.sourceHandle === handle))));
  }, [setEdges]);

  const save = useMutation({
    mutationFn: () => put(`/workflows/${workflowId}/graph`, toGraph(nodes, edges)),
    onSuccess: () => void qc.invalidateQueries(),
  });

  const addNode = (type: NodeType) => {
    const nid = newNodeId(type);
    setNodes((ns) => [...ns, { id: nid, type: "step", position: { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 },
      data: { type, label: NODE_SPECS[type].label.en, config: structuredClone(NODE_SPECS[type].defaultConfig) } }]);
    setSelected(nid);
  };
  const selectedNode = nodes.find((n) => n.id === selected);

  return (
    <div className="grid h-[calc(100vh-130px)] grid-cols-12">
      <div className="col-span-2 space-y-1 overflow-y-auto border-e bg-card p-3">
        <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Add a step</div>
        {NODE_TYPES.filter((t) => t !== "start").map((t) => (
          <button key={t} onClick={() => addNode(t)} className="flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-start text-sm hover:bg-accent">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: NODE_SPECS[t].color }} /> {NODE_SPECS[t].label.en}
          </button>
        ))}
      </div>
      <div className="col-span-7">
        <ReactFlow nodes={displayNodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)} fitView
          fitViewOptions={{ nodes: initialFocus, maxZoom: 1, padding: 0.2 }} minZoom={0.2}
          defaultEdgeOptions={{ style: { strokeWidth: 1.5 } }}>
          <Background /><Controls /><MiniMap pannable zoomable />
        </ReactFlow>
      </div>
      <div className="col-span-3 space-y-3 overflow-y-auto border-s bg-card p-3">
        <div className="flex gap-2">
          <Button className="flex-1" onClick={() => save.mutate()} disabled={save.isPending}><Save className="h-4 w-4" /> Save workflow</Button>
        </div>
        <ErrorBox error={save.error} />
        {save.isSuccess && <Alert variant="success">Saved (revision {(save.data as any)?.revision}).</Alert>}
        {issues.length > 0 && (
          <Card><CardContent className="space-y-1 p-3 text-xs">
            {issues.map((i, k) => (
              <button key={k} className={`block text-start ${i.severity === "error" ? "text-red-600" : "text-amber-600"}`}
                onClick={() => i.nodeId && setSelected(i.nodeId)}>• {i.message}</button>
            ))}
          </CardContent></Card>
        )}
        {selectedNode ? (
          <NodeEditor node={selectedNode} edges={edges} variables={variables} toolNames={enabledTools}
            onChange={(patch) => setNodes((ns) => ns.map((n) => (n.id === selectedNode.id ? { ...n, data: { ...n.data, ...patch } } : n)))}
            onEdgeChange={(eid, patch) => setEdges((es) => es.map((e) => (e.id === eid ? { ...e, ...patch } : e)))}
            onDelete={() => { setNodes((ns) => ns.filter((n) => n.id !== selectedNode.id)); setEdges((es) => es.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id)); setSelected(null); }} />
        ) : <p className="text-sm text-muted-foreground">Select a step to edit it. Drag from a step&apos;s bottom handles to connect it.</p>}
      </div>
    </div>
  );
}

export default function BuilderPage() {
  const { id } = useParams<{ id: string }>();
  const agent = useAgent(id);
  const save = useSaveAgentConfig(id);
  const create = useMutation({
    mutationFn: () => post<WorkflowSummary>("/workflows", { name: `${agent.data?.name} workflow`, agent_id: id }),
    onSuccess: (wf) => agent.data && save.mutate({ ...agent.data.draft_config, workflow_id: wf.id }),
  });
  if (!agent.data) return <div className="p-6"><Spinner /></div>;
  const wfId = agent.data.draft_config.workflow_id;
  if (!wfId) {
    return (
      <div className="mx-auto max-w-xl p-10 text-center">
        <p className="mb-4 text-sm text-muted-foreground">This agent has no workflow yet. Workflows let you control the conversation step by step.</p>
        <ErrorBox error={create.error ?? save.error} />
        <Button onClick={() => create.mutate()} disabled={create.isPending}>Create workflow</Button>
      </div>
    );
  }
  return (
    <ReactFlowProvider>
      {agent.data.draft_config.execution_mode !== "workflow" && (
        <Alert variant="warning" className="m-3">This agent currently runs in &quot;AI decides&quot; mode. Switch to &quot;Follow my visual workflow&quot; in General settings to use this workflow on calls.</Alert>
      )}
      <Builder workflowId={wfId} />
    </ReactFlowProvider>
  );
}
