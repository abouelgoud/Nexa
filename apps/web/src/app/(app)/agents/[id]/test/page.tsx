"use client";

import type { AudioClip, TestSession, TurnResult } from "@nexa/shared-types";
import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select, Spinner, cn } from "@nexa/ui";
import { Mic, PhoneOff, Send, Square } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { RealtimeTest } from "@/components/realtime-test";
import { api, post } from "@/lib/api";
import { dialectName } from "@/lib/format";
import { toWav16k } from "@/lib/wav";

type Line = { role: "agent" | "caller"; text: string };

function useAudioQueue() {
  const queue = useRef<string[]>([]);
  const current = useRef<HTMLAudioElement | null>(null);
  const playNext = () => {
    const src = queue.current.shift();
    if (!src) { current.current = null; return; }
    const a = new Audio(src);
    current.current = a;
    a.onended = playNext;
    a.play().catch(playNext);
  };
  return {
    enqueue(clips: AudioClip[]) {
      clips.filter((c) => c.audio_base64).forEach((c) => queue.current.push(`data:${c.mime_type ?? "audio/wav"};base64,${c.audio_base64}`));
      if (!current.current) playNext();
    },
    /** Barge-in: the caller started speaking, stop the agent immediately. */
    stop() {
      queue.current = [];
      current.current?.pause();
      current.current = null;
    },
  };
}

function DebugPanel({ last, mode, version }: { last: TurnResult | null; mode?: string; version?: TestSession["agent_version"] }) {
  if (!last) return <p className="text-sm text-muted-foreground">Start a call to see what the agent understands and does.</p>;
  return (
    <div className="space-y-3 text-sm">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">Language</div>
          {last.language === "ar" ? "Arabic" : last.language === "en" ? "English" : "-"} {last.code_switching && <Badge variant="secondary">mixed</Badge>}</div>
        <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">Dialect (probabilistic)</div>
          {dialectName(last.dialect)} {last.dialect && <span className="text-xs text-muted-foreground">{Math.round(last.dialect_confidence * 100)}%</span>}</div>
        <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">Intent</div>{last.intent ?? "-"}</div>
        <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">Mode / version</div>{mode} · v{version?.number} ({version?.kind})</div>
      </div>
      {Object.keys(last.latency_ms).length > 0 && (
        <div className="flex flex-wrap gap-2">{Object.entries(last.latency_ms).map(([k, v]) => <Badge key={k} variant="outline">{k}: {Math.round(v)} ms</Badge>)}</div>
      )}
      <div>
        <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Actions this turn</div>
        {last.tool_calls.length === 0 && <p className="text-xs text-muted-foreground">None</p>}
        {last.tool_calls.map((t, i) => (
          <details key={i} className="mb-1 rounded-md border p-2">
            <summary className="flex cursor-pointer items-center justify-between">
              <span className="font-mono text-xs">{t.tool}</span>
              <Badge variant={t.status === "succeeded" ? "success" : t.status === "confirmation_required" ? "warning" : "danger"}>{t.status}</Badge>
            </summary>
            <pre dir="auto" className="mt-2 max-h-56 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify({ arguments: t.arguments, result: t.data, error: t.error }, null, 2)}</pre>
          </details>
        ))}
      </div>
      {last.workflow && (
        <div>
          <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Workflow</div>
          <div className="text-xs">Step: <b>{last.workflow.current}</b> · {last.workflow.status}</div>
          <div className="mt-1 flex flex-wrap gap-1">{last.workflow.path.map((p, i) => <Badge key={i} variant="outline">{p}</Badge>)}</div>
          <pre dir="auto" className="mt-2 max-h-56 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(last.workflow.variables, null, 2)}</pre>
        </div>
      )}
      {last.actions.length > 0 && <Alert variant="warning">Call action: {last.actions.map((a) => a.type === "transfer" ? `transfer to ${a.label} (${a.phone_number})` : a.type).join(", ")}</Alert>}
    </div>
  );
}

export default function TestPage() {
  const { id } = useParams<{ id: string }>();
  const [use, setUse] = useState<"draft" | "published">("draft");
  const [mode, setMode] = useState<"turns" | "realtime">("turns");
  const [session, setSession] = useState<TestSession | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [last, setLast] = useState<TurnResult | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [ended, setEnded] = useState(false);
  const [intent, setIntent] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [voice, setVoice] = useState(true);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audio = useAudioQueue();
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [lines]);

  const apply = (result: TurnResult, clips: AudioClip[], callerText?: string) => {
    if (result.intent) setIntent(result.intent);
    setLines((l) => [...l, ...(callerText ? [{ role: "caller" as const, text: callerText }] : []),
      ...result.replies.map((r) => ({ role: "agent" as const, text: r }))]);
    setLast(result);
    if (voice) audio.enqueue(clips);
    if (result.ended || result.transferred) setEnded(true);
    const audioErr = clips.find((c) => c.error);
    if (audioErr) setError(new Error(`Voice playback unavailable: ${audioErr.error}`));
  };

  const start = async () => {
    setBusy(true); setError(null); setLines([]); setLast(null); setEnded(false); setIntent(null);
    try {
      const s = await post<TestSession>(`/test/sessions?voice=${voice}`, { agent_id: id, use });
      setSession(s);
      apply(s.result, s.audio);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const sendText = async () => {
    if (!session || !text.trim()) return;
    const t = text;
    setText(""); setBusy(true); setError(null); audio.stop();
    try {
      const r = await post<{ result: TurnResult; audio: AudioClip[] }>(`/test/sessions/${session.session_id}/messages?voice=${voice}`, { text: t });
      apply(r.result, r.audio, t);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const startRecording = async () => {
    audio.stop();
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const rec = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : undefined });
      chunks.current = [];
      rec.ondataavailable = (e) => chunks.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (!session) return;
        const recorded = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
        const wav = await toWav16k(recorded).catch(() => null);
        const form = new FormData();
        if (wav) form.append("file", wav, "speech.wav");
        else form.append("file", recorded, "speech.webm");
        form.append("voice", String(voice));
        setBusy(true);
        try {
          const r = await api<{ transcript: string; result: TurnResult; audio: AudioClip[] }>(`/test/sessions/${session.session_id}/audio`, { method: "POST", form });
          apply(r.result, r.audio, r.transcript || "(silence)");
        } catch (e) { setError(e); } finally { setBusy(false); }
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
    } catch {
      setError(new Error("Microphone access was blocked. Allow the microphone or type your message instead."));
    }
  };
  const stopRecording = () => { recorder.current?.stop(); setRecording(false); };

  const end = async () => {
    if (!session) return;
    audio.stop();
    await post(`/test/sessions/${session.session_id}/end`).catch(() => undefined);
    setEnded(true);
  };

  const connected = !!session && !ended;
  const modeSwitch = (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">Test mode:</span>
      <Button size="sm" variant={mode === "turns" ? "default" : "outline"} onClick={() => setMode("turns")}>Push-to-talk & text</Button>
      <Button size="sm" variant={mode === "realtime" ? "default" : "outline"} onClick={() => setMode("realtime")}>Real-time (WebRTC)</Button>
    </div>
  );
  if (mode === "realtime") {
    return <div className="space-y-4 p-6">{modeSwitch}<RealtimeTest agentId={id} use={use} /></div>;
  }
  return (
    <div className="space-y-4 p-6">
    {modeSwitch}
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2">Test agent
            <span className={cn("inline-flex items-center gap-1 text-xs font-normal", connected ? "text-emerald-600" : "text-muted-foreground")}>
              <span className={cn("h-2 w-2 rounded-full", connected ? "bg-emerald-500" : "bg-muted-foreground")} />{connected ? "Connected" : "Not connected"}
            </span>
          </CardTitle>
          <div className="flex items-center gap-2">
            <Select className="w-36" value={use} onChange={(e) => setUse(e.target.value as any)} disabled={connected}>
              <option value="draft">Draft</option><option value="published">Published</option>
            </Select>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} /> voice</label>
            {connected ? <Button variant="destructive" onClick={end}><PhoneOff className="h-4 w-4" /> End call</Button>
              : <Button onClick={start} disabled={busy}>Start call</Button>}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="h-[460px] space-y-2 overflow-y-auto rounded-lg bg-muted/40 p-3">
            {lines.length === 0 && <p className="pt-20 text-center text-sm text-muted-foreground">Press Start call, then speak (hold the mic) or type - in Arabic, English or both.</p>}
            {lines.map((l, i) => (
              <div key={i} className={cn("flex", l.role === "caller" ? "justify-end" : "justify-start")}>
                <div dir="auto" className={cn("max-w-[80%] rounded-2xl px-3 py-2 text-sm",
                  l.role === "caller" ? "bg-primary text-primary-foreground" : "border bg-card")}>{l.text}</div>
              </div>
            ))}
            {busy && <Spinner className="text-muted-foreground" />}
            <div ref={bottom} />
          </div>
          <ErrorBox error={error} />
          <div className="flex gap-2">
            <Button variant={recording ? "destructive" : "outline"} size="icon" disabled={!connected || (busy && !recording)}
              onPointerDown={startRecording} onPointerUp={stopRecording} onPointerLeave={() => recording && stopRecording()}
              title="Hold to talk">{recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}</Button>
            <Input dir="auto" placeholder="اكتب رسالة… / type a message…" value={text} disabled={!connected}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendText()} />
            <Button onClick={sendText} disabled={!connected || busy || !text.trim()}><Send className="h-4 w-4" /></Button>
          </div>
          {session && ended && <p className="text-sm text-muted-foreground">Call ended. <Link className="text-primary hover:underline" href={`/calls/${session.session_id}`}>Inspect the full call →</Link></p>}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle className="text-sm">Live debugging</CardTitle></CardHeader>
        <CardContent><DebugPanel last={last && { ...last, intent: last.intent ?? intent }} mode={session?.mode} version={session?.agent_version} /></CardContent>
      </Card>
    </div>
    </div>
  );
}
