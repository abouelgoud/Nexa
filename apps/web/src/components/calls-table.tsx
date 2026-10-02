"use client";

import type { CallSummary } from "@nexa/shared-types";
import { Badge, Card, CardContent, EmptyState } from "@nexa/ui";
import Link from "next/link";

import { OUTCOME_VARIANT, dialectName, duration, formatDate } from "@/lib/format";

export function CallsTable({ calls }: { calls: CallSummary[] }) {
  if (calls.length === 0) return <EmptyState title="No calls yet" description="Test your agent in the browser or call its phone number." />;
  return (
    <Card>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b text-xs text-muted-foreground">
            <tr className="text-start">{["Started", "Channel", "Caller", "Duration", "Language", "Dialect", "Intent", "Outcome"].map((h) =>
              <th key={h} className="px-4 py-2 text-start font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {calls.map((c) => (
              <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                <td className="px-4 py-2"><Link href={`/calls/${c.id}`} className="text-primary hover:underline">{formatDate(c.started_at)}</Link></td>
                <td className="px-4 py-2">{c.channel}{c.is_test && <Badge variant="outline" className="ms-1">test</Badge>}</td>
                <td className="px-4 py-2" dir="ltr">{c.from_number ?? "-"}</td>
                <td className="px-4 py-2">{duration(c.duration_seconds)}</td>
                <td className="px-4 py-2">{c.language ?? "-"}</td>
                <td className="px-4 py-2">{dialectName(c.dialect)}</td>
                <td className="px-4 py-2">{c.intent ?? "-"}</td>
                <td className="px-4 py-2">{c.outcome ? <Badge variant={OUTCOME_VARIANT[c.outcome] ?? "secondary"}>{c.outcome.replace(/_/g, " ")}</Badge> : <Badge variant="outline">{c.status}</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
