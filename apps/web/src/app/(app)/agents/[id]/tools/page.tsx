"use client";

import type { Integration, Tool } from "@nexa/shared-types";
import {
  Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Input, Label, Select,
  Switch, Textarea,
} from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Play, ShieldCheck, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { get, post } from "@/lib/api";
import { useAgent, useIntegrations, useSaveAgentConfig, useTools } from "@/lib/queries";

const OPERATION_LABELS: Record<string, string> = {
  get_record: "Find one record", search_records: "Search records", create_record: "Create a record",
  update_record: "Update a record", delete_record: "Delete a record",
};
const OP_PERMISSION: Record<string, string> = { get_record: "read", search_records: "read", create_record: "create",
  update_record: "update", delete_record: "delete" };

type Row = Record<string, string>;

function Rows({ rows, setRows, columns, addLabel }: {
  rows: Row[]; setRows: (r: Row[]) => void; columns: { key: string; placeholder: string; options?: string[] }[]; addLabel: string;
}) {
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex gap-2">
          {columns.map((c) => c.options ? (
            <Select key={c.key} value={r[c.key] ?? ""} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [c.key]: e.target.value } : x)))}>
              <option value="">{c.placeholder}</option>
              {c.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </Select>
          ) : (
            <Input key={c.key} placeholder={c.placeholder} value={r[c.key] ?? ""}
              onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [c.key]: e.target.value } : x)))} />
          ))}
          <Button type="button" variant="ghost" size="icon" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => setRows([...rows, {}])}><Plus className="h-3.5 w-3.5" /> {addLabel}</Button>
    </div>
  );
}

function inputsSchema(inputs: Row[]) {
  const properties: Record<string, any> = {};
  const required: string[] = [];
  for (const i of inputs) {
    if (!i.name) continue;
    properties[i.name] = { type: i.type || "string", ...(i.description ? { description: i.description } : {}) };
    if (i.required === "yes") required.push(i.name);
  }
  return { type: "object", properties, ...(required.length ? { required } : {}) };
}

function ActionBuilder({ integrations, onCreated }: { integrations: Integration[]; onCreated: (t: Tool) => void }) {
  const [kind, setKind] = useState<"database" | "rest_api">("database");
  const [meta, setMeta] = useState({ name: "", display_name: "", description: "", requires_confirmation: false });
  const [integrationId, setIntegrationId] = useState("");
  const [db, setDb] = useState({ operation: "search_records", table: "", limit: "10" });
  const [rest, setRest] = useState({ method: "GET", path: "/" });
  const [inputs, setInputs] = useState<Row[]>([]);
  const [filters, setFilters] = useState<Row[]>([]);
  const [values, setValues] = useState<Row[]>([]);
  const [returns, setReturns] = useState<string[]>([]);
  const [query, setQuery] = useState<Row[]>([]);
  const [body, setBody] = useState<Row[]>([]);
  const [mapping, setMapping] = useState<Row[]>([]);
  const conns = integrations.filter((i) => i.kind === kind);
  const integ = conns.find((c) => c.id === integrationId) ?? conns[0];
  const sharedTables: Record<string, any> = integ?.kind === "postgres" ? integ.config.permissions?.tables ?? {} : {};
  const table = sharedTables[db.table];
  const readable = Object.entries(table?.fields ?? {}).filter(([, p]) => p === "read" || p === "read_write").map(([f]) => f);
  const writable = Object.entries(table?.fields ?? {}).filter(([, p]) => p === "write" || p === "read_write").map(([f]) => f);
  const inputNames = inputs.map((i) => i.name).filter(Boolean);
  const tmpl = (v: string) => (inputNames.includes(v) ? `{{${v}}}` : v);

  const create = useMutation({
    mutationFn: () => {
      const [schemaName, tableName] = db.table.includes(".") ? db.table.split(".") : ["public", db.table];
      const config = kind === "database" ? {
        integration_id: integ?.id, operation: db.operation, db_schema: schemaName, table: tableName,
        limit: Number(db.limit) || 10, return_fields: returns,
        filters: filters.filter((f) => f.field).map((f) => ({ field: f.field, op: f.op || "eq",
          ...(inputNames.includes(f.source) ? { arg: f.source, optional: f.optional === "yes" } : { value: f.source }) })),
        values: Object.fromEntries(values.filter((v) => v.field).map((v) => [v.field, tmpl(v.source)])),
      } : {
        integration_id: integ?.id, method: rest.method, path: rest.path,
        query: Object.fromEntries(query.filter((q) => q.key).map((q) => [q.key, tmpl(q.source)])),
        body: body.length ? Object.fromEntries(body.filter((b) => b.key).map((b) => [b.key, tmpl(b.source)])) : null,
        response_mapping: Object.fromEntries(mapping.filter((m) => m.key).map((m) => [m.key, m.path])),
      };
      return post<Tool>("/tools", { ...meta, category: kind === "database" ? "database" : "rest_api", executor: kind,
        input_schema: inputsSchema(inputs), config });
    },
    onSuccess: onCreated,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>New action</CardTitle>
        <CardDescription>Describe what the action does in plain words. The AI only fills in the inputs - your rules decide everything else.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Button type="button" size="sm" variant={kind === "database" ? "default" : "outline"} onClick={() => setKind("database")}>Database action</Button>
          <Button type="button" size="sm" variant={kind === "rest_api" ? "default" : "outline"} onClick={() => setKind("rest_api")}>API action</Button>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label>Action id</Label><Input placeholder="get_order_status" value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></div>
          <div className="space-y-1"><Label>Display name</Label><Input placeholder="Get order status" value={meta.display_name} onChange={(e) => setMeta({ ...meta, display_name: e.target.value })} /></div>
          <div className="space-y-1 md:col-span-2"><Label>What does it do? (the AI reads this)</Label>
            <Textarea rows={2} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></div>
          <div className="space-y-1"><Label>Connection</Label>
            <Select value={integ?.id ?? ""} onChange={(e) => setIntegrationId(e.target.value)}>
              {conns.length === 0 && <option value="">Add a connection in Integrations first</option>}
              {conns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div><div className="text-sm font-medium">Ask the caller to confirm first</div><div className="text-xs text-muted-foreground">Use for bookings, cancellations and changes.</div></div>
            <Switch checked={meta.requires_confirmation} onCheckedChange={(v) => setMeta({ ...meta, requires_confirmation: v })} />
          </div>
        </div>
        <div className="space-y-2">
          <Label>Information the AI must provide (inputs)</Label>
          <Rows rows={inputs} setRows={setInputs} addLabel="Add input" columns={[
            { key: "name", placeholder: "order_id" }, { key: "type", placeholder: "type", options: ["string", "integer", "number", "boolean"] },
            { key: "required", placeholder: "required?", options: ["yes", "no"] }, { key: "description", placeholder: "description" }]} />
        </div>
        {kind === "database" ? (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-1"><Label>Operation</Label>
                <Select value={db.operation} onChange={(e) => setDb({ ...db, operation: e.target.value })}>
                  {Object.entries(OPERATION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </Select></div>
              <div className="space-y-1"><Label>Table (only shared tables)</Label>
                <Select value={db.table} onChange={(e) => { setDb({ ...db, table: e.target.value }); setReturns([]); }}>
                  <option value="">Choose…</option>
                  {Object.entries(sharedTables).filter(([, r]: any) => r.operations?.includes(OP_PERMISSION[db.operation]))
                    .map(([k]) => <option key={k} value={k}>{k}</option>)}
                </Select></div>
              <div className="space-y-1"><Label>Max results</Label><Input value={db.limit} onChange={(e) => setDb({ ...db, limit: e.target.value })} /></div>
            </div>
            {db.table && (<>
              <div className="space-y-1"><Label>Find records where</Label>
                <Rows rows={filters} setRows={setFilters} addLabel="Add condition" columns={[
                  { key: "field", placeholder: "field", options: readable }, { key: "op", placeholder: "equals", options: ["eq", "ne", "lt", "lte", "gt", "gte", "ilike"] },
                  { key: "source", placeholder: "input name or fixed value" }, { key: "optional", placeholder: "skip if missing?", options: ["yes", "no"] }]} /></div>
              {(db.operation === "create_record" || db.operation === "update_record") && (
                <div className="space-y-1"><Label>Save these values</Label>
                  <Rows rows={values} setRows={setValues} addLabel="Add value" columns={[
                    { key: "field", placeholder: "field", options: writable }, { key: "source", placeholder: "input name or fixed value" }]} /></div>
              )}
              <div className="space-y-1"><Label>Return these fields to the AI</Label>
                <div className="flex flex-wrap gap-3 text-sm">
                  {readable.map((f) => (
                    <label key={f} className="flex items-center gap-1.5">
                      <input type="checkbox" checked={returns.includes(f)} onChange={(e) => setReturns(e.target.checked ? [...returns, f] : returns.filter((x) => x !== f))} /> {f}
                    </label>
                  ))}
                </div></div>
            </>)}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="space-y-1"><Label>Method</Label>
                <Select value={rest.method} onChange={(e) => setRest({ ...rest, method: e.target.value })}>
                  {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}
                </Select></div>
              <div className="space-y-1 md:col-span-3"><Label>Endpoint path (use {"{input}"} for inputs)</Label>
                <Input value={rest.path} onChange={(e) => setRest({ ...rest, path: e.target.value })} placeholder="/orders/{order_id}" /></div>
            </div>
            <div className="space-y-1"><Label>Query parameters</Label>
              <Rows rows={query} setRows={setQuery} addLabel="Add parameter" columns={[{ key: "key", placeholder: "date" }, { key: "source", placeholder: "input name or fixed value" }]} /></div>
            {rest.method !== "GET" && (
              <div className="space-y-1"><Label>Body mapping (API field ← agent field)</Label>
                <Rows rows={body} setRows={setBody} addLabel="Add field" columns={[{ key: "key", placeholder: "customer.fullName" }, { key: "source", placeholder: "customer_name" }]} /></div>
            )}
            <div className="space-y-1"><Label>Response mapping (what the AI gets back)</Label>
              <Rows rows={mapping} setRows={setMapping} addLabel="Add mapping" columns={[{ key: "key", placeholder: "status" }, { key: "path", placeholder: "data.order.status" }]} /></div>
          </div>
        )}
        <ErrorBox error={create.error} />
        <Button onClick={() => create.mutate()} disabled={create.isPending || !meta.name || !integ}>Create action</Button>
      </CardContent>
    </Card>
  );
}

function TestAction({ tool }: { tool: Tool }) {
  const props = Object.keys((tool.definition.input_schema as any)?.properties ?? {});
  const [args, setArgs] = useState<Record<string, string>>({});
  const run = useMutation({ mutationFn: () => post(`/tools/${tool.id}/test`, { arguments: args }) });
  return (
    <div className="space-y-2 rounded-lg bg-muted/50 p-3">
      <div className="flex flex-wrap gap-2">
        {props.map((p) => <Input key={p} className="w-40" placeholder={p} value={args[p] ?? ""} onChange={(e) => setArgs({ ...args, [p]: e.target.value })} />)}
        <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending}><Play className="h-3.5 w-3.5" /> Run</Button>
      </div>
      {tool.definition.requires_confirmation && <p className="text-xs text-amber-600">Test runs execute for real (as if confirmed).</p>}
      <ErrorBox error={run.error} />
      {run.data && <pre dir="auto" className="max-h-64 overflow-auto rounded bg-background p-2 text-xs">{JSON.stringify(run.data, null, 2)}</pre>}
    </div>
  );
}

export default function ToolsPage() {
  const { id } = useParams<{ id: string }>();
  const agent = useAgent(id);
  const tools = useTools();
  const integrations = useIntegrations();
  const save = useSaveAgentConfig(id);
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["tool-catalog"], queryFn: () => get("/tools/catalog") });
  const [testing, setTesting] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const enabled = new Set(agent.data?.draft_config.tool_ids ?? []);
  const toggle = (toolId: string, on: boolean) => {
    if (!agent.data) return;
    const ids = on ? [...enabled, toolId] : [...enabled].filter((x) => x !== toolId);
    save.mutate({ ...agent.data.draft_config, tool_ids: ids });
  };
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <Alert variant="info" className="flex gap-2">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        <span>The agent can only use the actions switched on below. Every request is checked against your permissions, logged, and actions marked &quot;confirm first&quot; never run without the caller saying yes.</span>
      </Alert>
      <ErrorBox error={save.error} />
      {tools.data?.length === 0 && <EmptyState title="No actions yet" description="Create an action, or finish the template setup in Integrations." />}
      {tools.data?.map((t) => (
        <Card key={t.id}>
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2 font-medium">
                  {t.display_name || t.name}
                  <Badge variant="outline">{t.category}</Badge>
                  {t.definition.requires_confirmation && <Badge variant="warning">confirm first</Badge>}
                  <span className="text-xs text-muted-foreground">v{t.current_version}</span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{t.description}</p>
              </div>
              <div className="flex items-center gap-3">
                <Button size="sm" variant="ghost" onClick={() => setTesting(testing === t.id ? null : t.id)}>Test</Button>
                <Switch checked={enabled.has(t.id)} onCheckedChange={(v) => toggle(t.id, v)} />
              </div>
            </div>
            {testing === t.id && <TestAction tool={t} />}
          </CardContent>
        </Card>
      ))}
      <Card>
        <CardHeader><CardTitle className="text-sm">Built-in actions</CardTitle>
          <CardDescription>Always available when enabled in settings (transfer requires human handoff; knowledge search requires a knowledge base).</CardDescription></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {catalog.data?.builtins.map((b: any) => <Badge key={b.name} variant="secondary">{b.display_name}</Badge>)}
        </CardContent>
      </Card>
      {building ? (
        <ActionBuilder integrations={integrations.data ?? []} onCreated={(t) => { setBuilding(false); void qc.invalidateQueries(); toggle(t.id, true); }} />
      ) : <Button onClick={() => setBuilding(true)}><Plus className="h-4 w-4" /> New action</Button>}
    </div>
  );
}
