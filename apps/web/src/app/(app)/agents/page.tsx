"use client";

import { Badge, Button, Card, CardContent, EmptyState, Spinner } from "@nexa/ui";
import { Bot, Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/app-shell";
import { formatDate } from "@/lib/format";
import { useAgents } from "@/lib/queries";

export default function AgentsPage() {
  const { data, isLoading } = useAgents();
  return (
    <>
      <PageHeader title="Agents" description="Each agent answers calls for your business using your settings, knowledge and actions."
        actions={<Link href="/agents/new"><Button><Plus className="h-4 w-4" /> New agent</Button></Link>} />
      <div className="grid gap-4 p-6 md:grid-cols-2 xl:grid-cols-3">
        {isLoading && <Spinner />}
        {data?.length === 0 && (
          <div className="md:col-span-3">
            <EmptyState title="No agents yet" description="Pick a template to get a working agent in minutes."
              action={<Link href="/agents/new"><Button>Create agent</Button></Link>} />
          </div>
        )}
        {data?.map((a) => (
          <Link key={a.id} href={`/agents/${a.id}`}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 font-medium"><Bot className="h-5 w-5 text-primary" /> {a.name}</div>
                  <Badge variant={a.status === "published" ? "success" : "secondary"}>{a.status}</Badge>
                </div>
                <p className="line-clamp-2 text-sm text-muted-foreground">{a.description || "No description"}</p>
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{a.template_key?.replace(/_/g, " ")}</span><span>Updated {formatDate(a.updated_at)}</span>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}
