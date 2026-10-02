"use client";

import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Input, Label, Select } from "@nexa/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Phone } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { del, post } from "@/lib/api";
import { usePhoneNumbers } from "@/lib/queries";

export default function PhonePage() {
  const { id } = useParams<{ id: string }>();
  const numbers = usePhoneNumbers(id);
  const qc = useQueryClient();
  const [form, setForm] = useState({ e164: "", purpose: "test", allowed: "", outbound_address: "", outbound_username: "", outbound_password: "" });
  const [dial, setDial] = useState("");
  const add = useMutation({
    mutationFn: () => post("/phone-numbers", { e164: form.e164, agent_id: id, purpose: form.purpose, trunk: {
      allowed_addresses: form.allowed ? form.allowed.split(",").map((s) => s.trim()) : [],
      outbound_address: form.outbound_address || undefined, outbound_username: form.outbound_username || undefined,
      outbound_password: form.outbound_password || undefined } }),
    onSuccess: () => void qc.invalidateQueries(),
  });
  const remove = useMutation({ mutationFn: (nid: string) => del(`/phone-numbers/${nid}`), onSuccess: () => void qc.invalidateQueries() });
  const call = useMutation({ mutationFn: (nid: string) => post(`/phone-numbers/${nid}/outbound-test`, { to: dial }) });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <Alert variant="info">
        Phone calls reach the agent through LiveKit SIP. Buy a number from any SIP carrier (Twilio, Telnyx, Plivo…), point its SIP trunk at your LiveKit SIP address, then connect the number here. Test numbers use the latest tested draft; production numbers always use the published version.
      </Alert>
      {numbers.data?.length === 0 && <EmptyState title="No phone numbers yet" description="Connect a number to call your agent from a real phone." />}
      {numbers.data?.map((n) => (
        <Card key={n.id}>
          <CardContent className="space-y-3 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-medium"><Phone className="h-4 w-4" /> <span dir="ltr">{n.e164}</span>
                <Badge variant={n.status === "active" ? "success" : n.status === "error" ? "danger" : "secondary"}>{n.status}</Badge>
                <Badge variant="outline">{n.purpose}</Badge><span className="text-xs text-muted-foreground">via {n.provider}</span></div>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(n.id)}>Remove</Button>
            </div>
            {n.provider_ref?.error && <Alert variant="error">{n.provider_ref.error}</Alert>}
            <div className="flex gap-2">
              <Input dir="ltr" placeholder="+9665XXXXXXXX - your mobile" value={dial} onChange={(e) => setDial(e.target.value)} />
              <Button variant="outline" onClick={() => call.mutate(n.id)} disabled={!dial || call.isPending}>Have the agent call me</Button>
            </div>
            {call.data && <Alert variant="success">Calling… (room {call.data.room})</Alert>}
            <ErrorBox error={call.error} />
          </CardContent>
        </Card>
      ))}
      <Card>
        <CardHeader><CardTitle>Connect a number</CardTitle><CardDescription>Inbound calls to this number will be answered by this agent.</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1"><Label>Phone number (E.164)</Label><Input dir="ltr" placeholder="+966112345678" value={form.e164} onChange={set("e164")} /></div>
          <div className="space-y-1"><Label>Purpose</Label><Select value={form.purpose} onChange={set("purpose")}><option value="test">Test</option><option value="production">Production</option></Select></div>
          <div className="space-y-1 md:col-span-2"><Label>Carrier IP addresses allowed to send calls (optional, comma separated)</Label><Input dir="ltr" value={form.allowed} onChange={set("allowed")} /></div>
          <div className="space-y-1"><Label>Outbound SIP address (for outbound test calls)</Label><Input dir="ltr" placeholder="example.pstn.twilio.com" value={form.outbound_address} onChange={set("outbound_address")} /></div>
          <div className="space-y-1"><Label>Outbound SIP username</Label><Input value={form.outbound_username} onChange={set("outbound_username")} /></div>
          <div className="space-y-1"><Label>Outbound SIP password</Label><Input type="password" value={form.outbound_password} onChange={set("outbound_password")} /></div>
          <div className="md:col-span-2"><ErrorBox error={add.error} /></div>
          <Button className="md:col-span-2" onClick={() => add.mutate()} disabled={!form.e164 || add.isPending}>Connect number</Button>
        </CardContent>
      </Card>
    </div>
  );
}
