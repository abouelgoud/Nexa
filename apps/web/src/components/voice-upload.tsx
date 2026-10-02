"use client";

import { Alert, Button, Input, Label, Select } from "@nexa/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { api } from "@/lib/api";

export interface LibraryVoice {
  id: string; name: string; provider: "neural" | "elevenlabs"; provider_label: string; voice_id: string;
  seconds: number | null; created_at: string; used_by: string[];
}
export interface CloneEngine { key: "neural" | "elevenlabs"; label: string; available: boolean }

/** Upload a recording, name it, and create a cloned voice (shared by the Voices page and agent settings). */
export function VoiceUpload({ engines, defaultEngine, onCreated }: {
  engines: CloneEngine[]; defaultEngine?: string; onCreated: (v: LibraryVoice) => void;
}) {
  const available = engines.filter((e) => e.available);
  const [name, setName] = useState("");
  const [engine, setEngine] = useState(defaultEngine ?? available[0]?.key ?? "neural");
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const create = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("provider", engine);
      form.append("consent", String(consent));
      form.append("file", file as File);
      return api<LibraryVoice>("/voices", { method: "POST", form });
    },
    onSuccess: (v) => {
      setName(""); setFile(null); setConsent(false); setInputKey((k) => k + 1);
      onCreated(v);
    },
  });
  return (
    <div className="space-y-3">
      {available.length === 0 && (
        <Alert variant="warning">
          No cloning engine is available. Start the natural voice service (on a Mac: scripts/voice-mac.sh; with an
          NVIDIA GPU: docker compose --profile neural up) or add an ElevenLabs API key on the server.
        </Alert>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="voice-name">Voice name</Label>
          <Input id="voice-name" dir="auto" placeholder="e.g. نورة - الاستقبال" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="voice-engine">Create with</Label>
          <Select id="voice-engine" value={engine} onChange={(e) => setEngine(e.target.value as typeof engine)}>
            {engines.map((e) => <option key={e.key} value={e.key} disabled={!e.available}>{e.label}{e.available ? "" : " (not set up)"}</option>)}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="voice-file">Recording</Label>
          <Input key={inputKey} id="voice-file" type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">One person speaking clearly, no music or background noise. At least 4 seconds; 10-30 seconds sounds closest.</p>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />
        I have the speaker&apos;s permission to create and use a voice from this recording.
      </label>
      <ErrorBox error={create.error} />
      <Button type="button" disabled={!name.trim() || !file || !consent || create.isPending || available.length === 0}
        onClick={() => create.mutate()}>
        {create.isPending ? "Creating voice…" : "Create voice"}
      </Button>
    </div>
  );
}
