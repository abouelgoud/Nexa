"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle, Spinner, cn } from "@nexa/ui";
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/app-shell";
import { OUTCOME_VARIANT, dialectName, duration, formatDate } from "@/lib/format";
import { useCall } from "@/lib/queries";

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useCall(id);
  if (isLoading || !data) return <div className="p-6"><Spinner /></div>;
  const c = data.call;
  const facts: [string, React.ReactNode][] = [
    ["Call ID", <span key="id" className="font-mono text-xs">{c.id}</span>],
    ["Agent version", data.agent_version ? `v${data.agent_version.version_number} (${data.agent_version.kind})` : "-"],
    ["Channel", `${c.channel}${c.is_test ? " (test)" : ""}`], ["Caller", c.from_number ?? "-"],
    ["Started", formatDate(c.started_at)], ["Duration", duration(c.duration_seconds)],
    ["Language", c.language ?? "-"], ["Dialect", dialectName(c.dialect)], ["Intent", c.intent ?? "-"],
    ["Outcome", c.outcome ? <Badge key="o" variant={OUTCOME_VARIANT[c.outcome] ?? "secondary"}>{c.outcome}</Badge> : c.status],
    ["Transfer", c.transferred_to ?? "-"], ["Avg response", c.metrics.avg_turn_latency_ms ? `${c.metrics.avg_turn_latency_ms} ms` : "-"],
  ];
  const errors = data.events.filter((e) => e.type.includes("error") || e.type === "output_guard");
  return (
    <>
      <PageHeader title="Call details" description={<Link href="/calls" className="hover:underline">← All calls</Link>} />
      <div className="grid gap-6 p-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle className="text-sm">Transcript</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {data.messages.length === 0 && <p className="text-sm text-muted-foreground">Transcript storage is turned off for this agent.</p>}
              {data.messages.map((m) => (
                <div key={m.seq} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                  <div className={cn("max-w-[80%] rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-primary text-primary-foreground" : "border bg-card")}>
                    <div dir="auto">{m.original_text ?? m.content}</div>
                    {m.role === "user" && m.normalized_text && m.normalized_text !== m.original_text && (
                      <div dir="auto" className="mt-1 text-[11px] opacity-75">normalized: {m.normalized_text}</div>)}
                    {m.role === "user" && (m.language || m.dialect) && (
                      <div className="mt-1 text-[10px] opacity-75">{m.language}{m.dialect && ` · ${dialectName(m.dialect)}`}{m.metadata?.code_switching && " · mixed"}</div>)}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-sm">Action executions</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {data.tool_executions.length === 0 && <p className="text-sm text-muted-foreground">No actions were used.</p>}
              {data.tool_executions.map((t) => (
                <details key={t.id} className="rounded-md border p-2">
                  <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono">{t.tool_name}</span>
                    <Badge variant={t.status === "succeeded" ? "success" : t.status === "confirmation_required" ? "warning" : "danger"}>{t.status}</Badge>
                    <Badge variant="outline">{t.source}</Badge>
                    {t.requires_confirmation && <Badge variant={t.confirmed ? "success" : "secondary"}>{t.confirmed ? "confirmed by caller" : "needs confirmation"}</Badge>}
                    <span className="text-xs text-muted-foreground">{t.latency_ms ? `${Math.round(t.latency_ms)} ms` : ""}</span>
                  </summary>
                  <pre dir="auto" className="mt-2 max-h-72 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify({ arguments: t.arguments, result: t.result, error: t.error }, null, 2)}</pre>
                </details>
              ))}
            </CardContent>
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle className="text-sm">Summary</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {facts.map(([k, v]) => <div key={k} className="flex justify-between gap-4"><span className="text-muted-foreground">{k}</span><span className="text-end">{v}</span></div>)}
            </CardContent>
          </Card>
          {data.workflow && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Workflow path</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <div className="flex flex-wrap gap-1">{data.workflow.path.map((p, i) => <Badge key={i} variant="outline">{p}</Badge>)}</div>
                <pre dir="auto" className="max-h-60 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(data.workflow.variables, null, 2)}</pre>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader><CardTitle className="text-sm">Errors & safeguards</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-xs">
              {errors.length === 0 && <p className="text-muted-foreground">None</p>}
              {errors.map((e, i) => <div key={i}><Badge variant="danger">{e.type}</Badge> {JSON.stringify(e.payload)}</div>)}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-sm">Timeline</CardTitle></CardHeader>
            <CardContent className="max-h-96 space-y-1 overflow-y-auto text-xs">
              {data.events.map((e, i) => (
                <div key={i} className="flex justify-between gap-2 border-b py-1 last:border-0">
                  <span>{e.type}{e.payload.node && <span className="text-muted-foreground"> · {e.payload.node}</span>}</span>
                  <span className="text-muted-foreground">{e.latency_ms ? `${Math.round(e.latency_ms)} ms` : new Date(e.created_at).toLocaleTimeString()}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
