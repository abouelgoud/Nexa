"use client";

import type { Integration } from "@nexa/shared-types";
import {
  Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Input, Label, Select,
  Spinner,
} from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Globe, Sparkles } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { get, patch, post } from "@/lib/api";
import { useAgent, useIntegrations } from "@/lib/queries";

const PERMS = ["deny", "read", "write", "read_write"] as const;
const OPS = ["read", "create", "update", "delete"] as const;

function TemplateSetup({ agentId }: { agentId: string }) {
  const integrations = useIntegrations();
  const qc = useQueryClient();
  const [integrationId, setIntegrationId] = useState("");
  const dbs = integrations.data?.filter((i) => i.kind === "postgres") ?? [];
  const setup = useMutation({
    mutationFn: () => post(`/agents/${agentId}/template/setup`, { integration_id: integrationId || dbs[0]?.id }),
    onSuccess: () => void qc.invalidateQueries(),
  });
  return (
    <Card className="border-primary/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-primary" /> Finish the template setup</CardTitle>
        <CardDescription>Connect the database that holds your doctors, slots and appointments. We will create the booking actions and the workflow for you.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {dbs.length === 0 ? <p className="text-sm text-muted-foreground">Add a database connection below first (or use the demo clinic database).</p> : (
          <Select value={integrationId || dbs[0]?.id} onChange={(e) => setIntegrationId(e.target.value)}>
            {dbs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        )}
        <ErrorBox error={setup.error} />
        {setup.isSuccess && <Alert variant="success">Done! Actions and workflow were created. Try it in the Testing tab.</Alert>}
        <Button disabled={!dbs.length || setup.isPending} onClick={() => setup.mutate()}>Create actions & workflow</Button>
      </CardContent>
    </Card>
  );
}

function PermissionEditor({ integration }: { integration: Integration }) {
  const qc = useQueryClient();
  const schema = useQuery({ queryKey: ["schema", integration.id], queryFn: () => get(`/integrations/${integration.id}/schema`) });
  const [perms, setPerms] = useState<Record<string, any>>(integration.config.permissions?.tables ?? {});
  const save = useMutation({
    mutationFn: () => patch(`/integrations/${integration.id}`, { config: { ...integration.config, permissions: { tables: perms } } }),
    onSuccess: () => void qc.invalidateQueries(),
  });
  if (schema.isLoading) return <Spinner />;
  if (schema.error) return <ErrorBox error={schema.error} />;
  const tables: { schema: string; table: string; columns: { name: string; type: string }[] }[] = schema.data.tables;
  const setTable = (key: string, value: any) => setPerms((p) => ({ ...p, [key]: value }));
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Choose exactly which tables and fields the AI may read or change. Everything else is denied. The AI never writes SQL.</p>
      {tables.map((t) => {
        const key = `${t.schema}.${t.table}`;
        const rule = perms[key];
        return (
          <details key={key} className="rounded-lg border p-3" open={!!rule}>
            <summary className="flex cursor-pointer items-center justify-between text-sm font-medium">
              <span>{key}</span>
              {rule ? <Badge variant="success">shared</Badge> : <Badge variant="outline">not shared</Badge>}
            </summary>
            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap gap-3 text-sm">
                {OPS.map((op) => (
                  <label key={op} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={rule?.operations?.includes(op) ?? false} onChange={(e) => {
                      const ops = new Set<string>(rule?.operations ?? []);
                      if (e.target.checked) ops.add(op); else ops.delete(op);
                      setTable(key, { operations: [...ops], fields: rule?.fields ?? {} });
                    }} /> {op}
                  </label>
                ))}
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {t.columns.map((c) => (
                  <div key={c.name} className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate">{c.name} <span className="text-xs text-muted-foreground">{c.type}</span></span>
                    <Select className="w-32" value={rule?.fields?.[c.name] ?? "deny"} onChange={(e) =>
                      setTable(key, { operations: rule?.operations ?? ["read"], fields: { ...(rule?.fields ?? {}), [c.name]: e.target.value } })}>
                      {PERMS.map((p) => <option key={p} value={p}>{p.replace("_", " & ")}</option>)}
                    </Select>
                  </div>
                ))}
              </div>
            </div>
          </details>
        );
      })}
      <ErrorBox error={save.error} />
      {save.isSuccess && <Alert variant="success">Permissions saved.</Alert>}
      <Button onClick={() => save.mutate()} disabled={save.isPending}>Save permissions</Button>
    </div>
  );
}

function NewConnection() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<"postgres" | "rest_api">("postgres");
  const [v, setV] = useState<Record<string, string>>({ port: "5432", auth: "none", auth_name: "X-API-Key" });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV((s) => ({ ...s, [k]: e.target.value }));
  const create = useMutation({
    mutationFn: () => {
      if (kind === "postgres") {
        return post("/integrations", { name: v.name, kind, config: { host: v.host, port: Number(v.port), database: v.database,
          username: v.username, ssl: v.ssl === "yes" }, credentials: { password: v.password } });
      }
      const headers = Object.fromEntries((v.headers ?? "").split("\n").map((l) => l.split(":").map((s) => s.trim()))
        .filter((p) => p.length === 2 && p[0]));
      const credentials: Record<string, string> = {};
      if (v.auth === "bearer") credentials.token = v.secret;
      if (v.auth === "api_key") credentials.api_key = v.secret;
      if (v.auth === "basic") { credentials.username = v.username; credentials.password = v.secret; }
      return post("/integrations", { name: v.name, kind, config: { base_url: v.base_url, default_headers: headers,
        auth: { type: v.auth, name: v.auth_name } }, credentials });
    },
    onSuccess: () => { setV({ port: "5432", auth: "none", auth_name: "X-API-Key" }); void qc.invalidateQueries(); },
  });
  const demo = useMutation({ mutationFn: () => post("/integrations/demo-clinic"), onSuccess: () => void qc.invalidateQueries() });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Add a connection</CardTitle>
        <CardDescription>Passwords and keys are encrypted and never shown again or sent to the AI.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Button variant={kind === "postgres" ? "default" : "outline"} size="sm" onClick={() => setKind("postgres")}><Database className="h-4 w-4" /> PostgreSQL</Button>
          <Button variant={kind === "rest_api" ? "default" : "outline"} size="sm" onClick={() => setKind("rest_api")}><Globe className="h-4 w-4" /> REST API</Button>
          <Button variant="ghost" size="sm" onClick={() => demo.mutate()} disabled={demo.isPending}>Use demo clinic database</Button>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label>Name</Label><Input value={v.name ?? ""} onChange={set("name")} placeholder="Clinic system" /></div>
          {kind === "postgres" ? (<>
            <div className="space-y-1"><Label>Host</Label><Input value={v.host ?? ""} onChange={set("host")} placeholder="db.example.com" /></div>
            <div className="space-y-1"><Label>Port</Label><Input value={v.port ?? ""} onChange={set("port")} /></div>
            <div className="space-y-1"><Label>Database</Label><Input value={v.database ?? ""} onChange={set("database")} /></div>
            <div className="space-y-1"><Label>User</Label><Input value={v.username ?? ""} onChange={set("username")} /></div>
            <div className="space-y-1"><Label>Password</Label><Input type="password" value={v.password ?? ""} onChange={set("password")} /></div>
            <div className="space-y-1"><Label>Require SSL</Label><Select value={v.ssl ?? "no"} onChange={set("ssl")}><option value="no">No</option><option value="yes">Yes</option></Select></div>
          </>) : (<>
            <div className="space-y-1"><Label>Base URL</Label><Input value={v.base_url ?? ""} onChange={set("base_url")} placeholder="https://api.example.com/v1" /></div>
            <div className="space-y-1"><Label>Authentication</Label>
              <Select value={v.auth} onChange={set("auth")}>
                <option value="none">None</option><option value="bearer">Bearer token</option>
                <option value="api_key">API key header</option><option value="basic">Username & password</option>
              </Select>
            </div>
            {v.auth === "api_key" && <div className="space-y-1"><Label>Header name</Label><Input value={v.auth_name} onChange={set("auth_name")} /></div>}
            {v.auth === "basic" && <div className="space-y-1"><Label>Username</Label><Input value={v.username ?? ""} onChange={set("username")} /></div>}
            {v.auth !== "none" && <div className="space-y-1"><Label>Secret</Label><Input type="password" value={v.secret ?? ""} onChange={set("secret")} /></div>}
            <div className="space-y-1 md:col-span-2"><Label>Extra headers (one per line, Name: value)</Label>
              <textarea className="min-h-16 w-full rounded-md border bg-background p-2 text-sm" value={v.headers ?? ""} onChange={(e) => setV((s) => ({ ...s, headers: e.target.value }))} />
            </div>
          </>)}
        </div>
        <ErrorBox error={create.error ?? demo.error} />
        <Button onClick={() => create.mutate()} disabled={create.isPending || !v.name}>Save connection</Button>
      </CardContent>
    </Card>
  );
}

function ConnectionCard({ integration }: { integration: Integration }) {
  const [open, setOpen] = useState(false);
  const test = useMutation({ mutationFn: () => post(`/integrations/${integration.id}/test`) });
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-medium">
            {integration.kind === "postgres" ? <Database className="h-4 w-4" /> : <Globe className="h-4 w-4" />}
            {integration.name}
            <Badge variant="outline">{integration.kind === "postgres" ? "PostgreSQL" : "REST API"}</Badge>
            {integration.has_credentials && <Badge variant="secondary">credentials saved {integration.credential_hint && `(${integration.credential_hint})`}</Badge>}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>Test connection</Button>
            {integration.kind === "postgres" && <Button size="sm" variant="outline" onClick={() => setOpen((o) => !o)}>Permissions</Button>}
          </div>
        </div>
        {test.data && <Alert variant={test.data.ok ? "success" : "warning"}>{test.data.message}</Alert>}
        <ErrorBox error={test.error} />
        {open && <PermissionEditor integration={integration} />}
      </CardContent>
    </Card>
  );
}

function IntegrationsInner() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const agent = useAgent(id);
  const integrations = useIntegrations();
  const needsSetup = agent.data?.template_key === "doctor_appointment" && (agent.data.draft_config.tool_ids.length === 0 || params.get("setup"));
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      {needsSetup && <TemplateSetup agentId={id} />}
      {integrations.data?.length === 0 && <EmptyState title="No connections yet" description="Connect a database or an API so the agent can look up and save information." />}
      {integrations.data?.map((i) => <ConnectionCard key={i.id} integration={i} />)}
      <NewConnection />
    </div>
  );
}

export default function IntegrationsPage() {
  return <Suspense><IntegrationsInner /></Suspense>;
}
