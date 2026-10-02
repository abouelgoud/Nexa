"use client";

import type { Member, Tenant } from "@nexa/shared-types";
import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Select } from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { ErrorBox } from "@/components/error-box";
import { del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function SettingsPage() {
  const auth = useAuth();
  const qc = useQueryClient();
  const tenant = useQuery({ queryKey: [auth.tenantId, "tenant"], queryFn: () => get<Tenant>("/tenants/current") });
  const members = useQuery({ queryKey: [auth.tenantId, "members"], queryFn: () => get<Member[]>("/tenants/current/members") });
  const usage = useQuery({ queryKey: [auth.tenantId, "usage"], queryFn: () => get("/analytics/usage") });
  const [form, setForm] = useState({ name: "", industry: "", default_timezone: "Asia/Riyadh" });
  const [invite, setInvite] = useState({ email: "", role: "editor" });
  const [newBiz, setNewBiz] = useState("");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initialise the form once the tenant loads
    if (tenant.data) setForm({ name: tenant.data.name, industry: tenant.data.industry ?? "", default_timezone: tenant.data.default_timezone });
  }, [tenant.data]);
  const save = useMutation({ mutationFn: () => patch("/tenants/current", form), onSuccess: () => { void qc.invalidateQueries(); void auth.refresh(); } });
  const add = useMutation({ mutationFn: () => post("/tenants/current/members", invite), onSuccess: () => { setInvite({ email: "", role: "editor" }); void qc.invalidateQueries(); } });
  const remove = useMutation({ mutationFn: (uid: string) => del(`/tenants/current/members/${uid}`), onSuccess: () => void qc.invalidateQueries() });
  const create = useMutation({ mutationFn: () => post<Tenant>("/tenants", { name: newBiz }), onSuccess: async (t) => { await auth.refresh(); auth.selectTenant(t.id); setNewBiz(""); } });
  return (
    <>
      <PageHeader title="Settings" description="Business, team and usage." />
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <Card>
          <CardHeader><CardTitle>Business</CardTitle></CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1"><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="space-y-1"><Label>Industry</Label><Input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></div>
            <div className="space-y-1"><Label>Timezone</Label><Input value={form.default_timezone} onChange={(e) => setForm({ ...form, default_timezone: e.target.value })} /></div>
            <div className="md:col-span-3"><ErrorBox error={save.error} />{save.isSuccess && <Alert variant="success">Saved.</Alert>}</div>
            <Button className="w-fit" onClick={() => save.mutate()}>Save</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Team</CardTitle><CardDescription>Owners and admins publish and manage connections; editors build and test; viewers can only look.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {members.data?.map((m) => (
              <div key={m.user_id} className="flex items-center justify-between rounded-md border p-2 text-sm">
                <span>{m.full_name || m.email} <span className="text-muted-foreground">{m.email}</span></span>
                <span className="flex items-center gap-2"><Badge variant="outline">{m.role}</Badge>
                  {m.user_id !== auth.user?.id && <Button size="sm" variant="ghost" onClick={() => remove.mutate(m.user_id)}>Remove</Button>}</span>
              </div>
            ))}
            <div className="flex gap-2">
              <Input placeholder="colleague@business.com" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
              <Select className="w-36" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                {["viewer", "editor", "admin", "owner"].map((r) => <option key={r}>{r}</option>)}
              </Select>
              <Button onClick={() => add.mutate()} disabled={!invite.email}>Add</Button>
            </div>
            <ErrorBox error={add.error ?? remove.error} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Usage (last 30 days)</CardTitle><CardDescription>Metered for future billing.</CardDescription></CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {["call_seconds", "audio_seconds", "llm_tokens", "stt_seconds", "tts_characters", "storage_bytes", "api_calls", "tool_executions"].map((m) => (
              <div key={m} className="rounded-md border p-3"><div className="text-xs text-muted-foreground">{m.replace(/_/g, " ")}</div>
                <div className="text-lg font-semibold">{Math.round(usage.data?.usage?.[m] ?? 0).toLocaleString()}</div></div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Another business</CardTitle><CardDescription>Each business (tenant) is fully isolated.</CardDescription></CardHeader>
          <CardContent className="flex gap-2">
            <Input placeholder="Business name" value={newBiz} onChange={(e) => setNewBiz(e.target.value)} />
            <Button onClick={() => create.mutate()} disabled={!newBiz}>Create</Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
