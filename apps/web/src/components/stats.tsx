"use client";

import type { Analytics } from "@nexa/shared-types";
import { Card, CardContent, CardHeader, CardTitle } from "@nexa/ui";

import { dialectName } from "@/lib/format";

export function StatGrid({ data }: { data: Analytics }) {
  const stats = [
    ["Calls", data.calls],
    ["Answered", data.answered_calls],
    ["Completed tasks", data.completed_tasks],
    ["Transferred", data.transferred_calls],
    ["Failed tasks", data.failed_tasks],
    ["Avg duration", `${data.avg_duration_seconds}s`],
    ["Avg response", `${Math.round(data.avg_response_latency_ms)} ms`],
    ["Satisfaction", data.customer_satisfaction ?? "-"],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {stats.map(([label, value]) => (
        <Card key={label as string}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-1 text-2xl font-semibold">{value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function Distribution({ title, items, format }: {
  title: string; items: { key: string; count: number }[]; format?: (k: string) => string;
}) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 && <p className="text-sm text-muted-foreground">No data yet.</p>}
        {items.map((i) => (
          <div key={i.key} className="space-y-1">
            <div className="flex justify-between text-xs"><span>{format ? format(i.key) : i.key}</span><span>{i.count}</span></div>
            <div className="h-1.5 rounded-full bg-muted">
              <div className="h-1.5 rounded-full bg-primary" style={{ width: `${(i.count / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function AnalyticsPanels({ data }: { data: Analytics }) {
  return (
    <div className="space-y-4">
      <StatGrid data={data} />
      <div className="grid gap-4 md:grid-cols-3">
        <Distribution title="Languages" items={data.languages} format={(k) => (k === "ar" ? "Arabic" : k === "en" ? "English" : k)} />
        <Distribution title="Arabic dialects" items={data.dialects} format={dialectName} />
        <Distribution title="Top intents" items={data.top_intents} />
        <Distribution title="Outcomes" items={data.outcomes} />
        <Distribution title="Tool failures" items={data.tool_failures.map((f) => ({ key: f.tool, count: f.count }))} />
        <Distribution title="Calls per day" items={data.calls_per_day.map((d) => ({ key: d.day, count: d.count }))} />
      </div>
    </div>
  );
}
