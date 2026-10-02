"use client";

import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Spinner } from "@nexa/ui";
import { useQuery } from "@tanstack/react-query";
import { Bot, Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/app-shell";
import { AnalyticsPanels } from "@/components/stats";
import { get } from "@/lib/api";
import { useAgents, useAnalytics } from "@/lib/queries";

function ProviderStatus() {
  const { data } = useQuery({ queryKey: ["providers"], queryFn: () => get("/test/providers"), refetchInterval: 30_000 });
  if (!data) return null;
  const items: [string, { healthy: boolean; provider: string; model?: string }][] = [
    ["Language model", data.llm], ["Speech recognition", data.stt], ["Voice", data.tts]];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">AI services {data.local_ai && <Badge variant="secondary" className="ms-2">local</Badge>}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {items.map(([label, s]) => (
          <div key={label} className="flex items-center justify-between">
            <span>{label} <span className="text-xs text-muted-foreground">({s.model ?? s.provider})</span></span>
            <Badge variant={s.healthy ? "success" : "warning"}>{s.healthy ? "online" : "offline"}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const agents = useAgents();
  const analytics = useAnalytics();
  return (
    <>
      <PageHeader title="Dashboard" description="Your AI phone agents at a glance."
        actions={<Link href="/agents/new"><Button><Plus className="h-4 w-4" /> New agent</Button></Link>} />
      <div className="space-y-6 p-6">
        {analytics.data ? <AnalyticsPanels data={analytics.data} /> : <Spinner />}
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle className="text-sm">Agents</CardTitle><CardDescription>Open an agent to configure, test and publish it.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {agents.data?.length === 0 && (
                <EmptyState title="No agents yet" description="Start from a template such as Doctor Appointment Booking."
                  action={<Link href="/agents/new"><Button>Create your first agent</Button></Link>} />
              )}
              {agents.data?.map((a) => (
                <Link key={a.id} href={`/agents/${a.id}`} className="flex items-center justify-between rounded-lg border p-3 hover:bg-accent">
                  <span className="flex items-center gap-2"><Bot className="h-4 w-4 text-primary" /> {a.name}</span>
                  <Badge variant={a.status === "published" ? "success" : "secondary"}>{a.status}</Badge>
                </Link>
              ))}
            </CardContent>
          </Card>
          <ProviderStatus />
        </div>
      </div>
    </>
  );
}
