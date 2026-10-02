"use client";

import { Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Input, Spinner } from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Mic, Pencil, Play, Trash2, X } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { ErrorBox } from "@/components/error-box";
import { VoiceUpload, type CloneEngine, type LibraryVoice } from "@/components/voice-upload";
import { API_URL, del, get, patch, post, session } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";

async function playRecording(id: string) {
  const res = await fetch(`${API_URL}/voices/${id}/recording`, {
    headers: { Authorization: `Bearer ${session.token}`, "X-Tenant-ID": session.tenant ?? "" } });
  if (res.ok) void new Audio(URL.createObjectURL(await res.blob())).play();
}

function VoiceRow({ voice, onChanged }: { voice: LibraryVoice; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(voice.name);
  const rename = useMutation({ mutationFn: () => patch(`/voices/${voice.id}`, { name }), onSuccess: () => { setEditing(false); onChanged(); } });
  const remove = useMutation({ mutationFn: () => del(`/voices/${voice.id}`), onSuccess: onChanged });
  const sample = useMutation({
    mutationFn: () => post<{ mime_type: string; audio_base64: string }>("/voices/preview",
      { provider: voice.provider, voice_id: voice.voice_id, language: "ar" }),
    onSuccess: (c) => void new Audio(`data:${c.mime_type};base64,${c.audio_base64}`).play(),
  });
  return (
    <div className="space-y-2 rounded-lg border p-3" data-testid="voice-row">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Mic className="h-4 w-4 shrink-0 text-primary" />
          {editing ? (
            <span className="flex items-center gap-1">
              <Input dir="auto" className="h-8 w-56" value={name} onChange={(e) => setName(e.target.value)} />
              <Button size="icon" variant="ghost" onClick={() => rename.mutate()} disabled={!name.trim()}><Check className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => { setEditing(false); setName(voice.name); }}><X className="h-4 w-4" /></Button>
            </span>
          ) : <span dir="auto" className="truncate font-medium">{voice.name}</span>}
          <Badge variant="outline">{voice.provider_label}</Badge>
          {voice.seconds && <span className="text-xs text-muted-foreground">{voice.seconds}s recording</span>}
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => void playRecording(voice.id)} title="Play the original recording"><Play className="h-3.5 w-3.5" /> Original</Button>
          <Button size="sm" variant="outline" onClick={() => sample.mutate()} disabled={sample.isPending}>
            {sample.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} Hear the clone
          </Button>
          {!editing && <Button size="icon" variant="ghost" onClick={() => setEditing(true)} title="Rename"><Pencil className="h-4 w-4" /></Button>}
          <Button size="icon" variant="ghost" onClick={() => remove.mutate()} title="Delete"><Trash2 className="h-4 w-4" /></Button>
        </div>
      </div>
      <div className="text-xs text-muted-foreground">
        Created {formatDate(voice.created_at)}{voice.used_by.length > 0 && <> · used by {voice.used_by.join(", ")}</>}
      </div>
      <ErrorBox error={remove.error ?? rename.error ?? sample.error} />
    </div>
  );
}

export default function VoicesPage() {
  const { tenantId } = useAuth();
  const qc = useQueryClient();
  const library = useQuery({ queryKey: [tenantId, "voices"], queryFn: () => get<{ voices: LibraryVoice[]; engines: CloneEngine[] }>("/voices") });
  const [created, setCreated] = useState<string | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: [tenantId, "voices"] });
    void qc.invalidateQueries({ queryKey: ["voice-catalog"] });
  };
  return (
    <>
      <PageHeader title="Voices" description="Your own voices. Upload a recording, give it a name, and pick it for any agent." />
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <Card>
          <CardHeader>
            <CardTitle>Add a voice</CardTitle>
            <CardDescription>Clone a real person&apos;s voice, e.g. your receptionist, so callers hear a familiar voice.</CardDescription>
          </CardHeader>
          <CardContent>
            {library.data && <VoiceUpload engines={library.data.engines} onCreated={(v) => { setCreated(v.name); refresh(); }} />}
            {created && <Alert variant="success" className="mt-3">&quot;{created}&quot; was created. Choose it in an agent&apos;s Voice settings.</Alert>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Your voices</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {library.isLoading && <Spinner />}
            {library.data?.voices.length === 0 && <EmptyState title="No voices yet" description="Upload a recording above to create your first voice." />}
            {library.data?.voices.map((v) => <VoiceRow key={v.id} voice={v} onChanged={refresh} />)}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
