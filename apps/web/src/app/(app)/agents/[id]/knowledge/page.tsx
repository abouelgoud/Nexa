"use client";

import type { KnowledgeDocument } from "@nexa/shared-types";
import {
  Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Input, Label, Switch, Textarea,
} from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, Search, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { api, del, get, post } from "@/lib/api";
import { useAgent, useKnowledgeBases, useSaveAgentConfig } from "@/lib/queries";

const STATUS: Record<string, "success" | "warning" | "danger" | "secondary"> = {
  ready: "success", processing: "warning", pending: "secondary", failed: "danger",
};

function KnowledgeBasePanel({ kbId }: { kbId: string }) {
  const qc = useQueryClient();
  const docs = useQuery({ queryKey: ["docs", kbId], queryFn: () => get<KnowledgeDocument[]>(`/knowledge/${kbId}/documents`),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false) });
  const [mode, setMode] = useState<"file" | "text" | "faq" | "url">("file");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [faq, setFaq] = useState([{ question: "", answer: "" }]);
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["docs", kbId] });
  const add = useMutation({
    mutationFn: () => {
      if (mode === "file" && file) {
        const form = new FormData();
        form.append("file", file);
        if (title) form.append("title", title);
        return api(`/knowledge/${kbId}/documents/upload`, { method: "POST", form });
      }
      return post(`/knowledge/${kbId}/documents`, {
        title: title || (mode === "url" ? url : "Notes"), source_type: mode,
        content: mode === "text" ? text : undefined, url: mode === "url" ? url : undefined,
        faq: mode === "faq" ? faq.filter((f) => f.question && f.answer) : undefined,
      });
    },
    onSuccess: () => { setTitle(""); setText(""); setUrl(""); setFile(null); setFaq([{ question: "", answer: "" }]); refresh(); },
  });
  const remove = useMutation({ mutationFn: (docId: string) => del(`/knowledge/${kbId}/documents/${docId}`), onSuccess: refresh });
  const search = useMutation({ mutationFn: () => post(`/knowledge/${kbId}/search`, { query }) });

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        {docs.data?.length === 0 && <p className="text-sm text-muted-foreground">No documents yet.</p>}
        {docs.data?.map((d) => (
          <div key={d.id} className="flex items-center justify-between rounded-md border p-2 text-sm">
            <span className="flex items-center gap-2"><FileText className="h-4 w-4" /> {d.title}
              <Badge variant="outline">{d.source_type}</Badge><Badge variant={STATUS[d.status]}>{d.status}</Badge>
              {d.status === "ready" && <span className="text-xs text-muted-foreground">{d.chunk_count} passages</span>}
              {d.error && <span className="text-xs text-destructive">{d.error}</span>}
            </span>
            <Button size="icon" variant="ghost" onClick={() => remove.mutate(d.id)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
      </div>
      <div className="space-y-3 rounded-lg border p-4">
        <div className="flex flex-wrap gap-2">
          {(["file", "text", "faq", "url"] as const).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? "default" : "outline"} onClick={() => setMode(m)}>
              {{ file: "Upload PDF / Word / TXT", text: "Write text", faq: "FAQ", url: "Website page" }[m]}
            </Button>
          ))}
        </div>
        <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        {mode === "file" && <Input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
        {mode === "text" && <Textarea dir="auto" rows={6} placeholder="Prices, services, policies, location…" value={text} onChange={(e) => setText(e.target.value)} />}
        {mode === "url" && <Input placeholder="https://www.example.com/services" value={url} onChange={(e) => setUrl(e.target.value)} />}
        {mode === "faq" && (
          <div className="space-y-2">
            {faq.map((f, i) => (
              <div key={i} className="grid gap-2 md:grid-cols-2">
                <Input dir="auto" placeholder="Question" value={f.question} onChange={(e) => setFaq(faq.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))} />
                <Input dir="auto" placeholder="Answer" value={f.answer} onChange={(e) => setFaq(faq.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)))} />
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => setFaq([...faq, { question: "", answer: "" }])}><Plus className="h-3.5 w-3.5" /> Add question</Button>
          </div>
        )}
        <ErrorBox error={add.error} />
        <Button onClick={() => add.mutate()} disabled={add.isPending}>Add to knowledge</Button>
      </div>
      <div className="space-y-2 rounded-lg border p-4">
        <Label>Try a question</Label>
        <div className="flex gap-2">
          <Input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="كم سعر الكشف؟" />
          <Button variant="outline" onClick={() => search.mutate()} disabled={!query}><Search className="h-4 w-4" /></Button>
        </div>
        {search.data?.results.length === 0 && <p className="text-sm text-muted-foreground">Nothing found - the agent would say it doesn&apos;t know.</p>}
        {search.data?.results.map((r: any) => (
          <div key={r.chunk_id} className="rounded-md bg-muted/50 p-2 text-sm" dir="auto">
            <div className="mb-1 text-xs text-muted-foreground">{r.document_title} · score {r.score}</div>{r.content}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const agent = useAgent(id);
  const kbs = useKnowledgeBases();
  const save = useSaveAgentConfig(id);
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({ mutationFn: () => post("/knowledge", { name }), onSuccess: (kb: any) => {
    setName(""); void qc.invalidateQueries();
    if (agent.data) save.mutate({ ...agent.data.draft_config, knowledge_base_ids: [...agent.data.draft_config.knowledge_base_ids, kb.id] });
  } });
  const attached = new Set(agent.data?.draft_config.knowledge_base_ids ?? []);
  const toggle = (kbId: string, on: boolean) => agent.data && save.mutate({ ...agent.data.draft_config,
    knowledge_base_ids: on ? [...attached, kbId] : [...attached].filter((x) => x !== kbId) });
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <p className="text-sm text-muted-foreground">The agent answers business questions only from this knowledge. If the answer is not here, it says so instead of guessing.</p>
      <ErrorBox error={save.error ?? create.error} />
      {kbs.data?.length === 0 && <EmptyState title="No knowledge yet" description="Create a knowledge base and add your prices, services, policies and FAQs." />}
      {kbs.data?.map((kb) => (
        <Card key={kb.id}>
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>{kb.name}</CardTitle><CardDescription>{kb.embedding_model}</CardDescription></div>
            <div className="flex items-center gap-2 text-sm">Used by this agent <Switch checked={attached.has(kb.id)} onCheckedChange={(v) => toggle(kb.id, v)} /></div>
          </CardHeader>
          <CardContent><KnowledgeBasePanel kbId={kb.id} /></CardContent>
        </Card>
      ))}
      <div className="flex gap-2">
        <Input placeholder="New knowledge base name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button onClick={() => create.mutate()} disabled={!name || create.isPending}>Create</Button>
      </div>
    </div>
  );
}
