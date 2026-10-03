"use client";

import type { CallDetail, CallSummary } from "@nexa/shared-types";
import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, cn } from "@nexa/ui";
import { PhoneOff, Radio, Volume2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ErrorBox } from "@/components/error-box";
import { get, post } from "@/lib/api";
import { dialectName } from "@/lib/format";

type RoomLike = { disconnect: () => Promise<void>; startAudio: () => Promise<void>; canPlaybackAudio: boolean };

/**
 * Real-time WebRTC test through LiveKit: the browser publishes the microphone, the Nexa voice runtime
 * (services/voice-runtime) joins the room and answers with VAD, streaming turns and barge-in.
 * The transcript and debugging data are read back from the call record as the call progresses.
 */
export function RealtimeTest({ agentId, use }: { agentId: string; use: "draft" | "published" }) {
  const [room, setRoom] = useState<RoomLike | null>(null);
  const [roomName, setRoomName] = useState<string | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallDetail | null>(null);
  const [status, setStatus] = useState("idle");
  const [agentJoined, setAgentJoined] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const audioHost = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!roomName) return;
    const timer = setInterval(async () => {
      try {
        let id = callId;
        if (!id) {
          const calls = await get<CallSummary[]>(`/calls?external_id=${roomName}`);
          id = calls[0]?.id ?? null;
          if (id) setCallId(id);
        }
        if (id) setDetail(await get<CallDetail>(`/calls/${id}`));
      } catch { /* keep polling */ }
    }, 1500);
    return () => clearInterval(timer);
  }, [roomName, callId]);

  // Explain stalls instead of waiting silently: the agent never joined, or joined but could not start the call.
  useEffect(() => {
    if (status !== "connected") return;
    const timer = setTimeout(() => {
      if (!agentJoined) {
        setProblem("The voice agent did not join the call. Make sure the voice-runtime service is running and up to date: " +
          "docker compose up -d --build voice-runtime  (logs: docker compose logs voice-runtime).");
      } else if (!callId) {
        setProblem("The voice agent joined but could not start the call. Check: docker compose logs voice-runtime.");
      }
    }, 20000);
    return () => clearTimeout(timer);
  }, [status, agentJoined, callId]);

  const start = async () => {
    setError(null); setDetail(null); setCallId(null); setStatus("connecting"); setAgentJoined(false); setProblem(null);
    try {
      const { Room, RoomEvent, Track } = await import("livekit-client");
      const info = await post<{ url: string; token: string; room: string }>("/test/realtime", { agent_id: agentId, use });
      const r = new Room({ adaptiveStream: true, dynacast: true });
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) audioHost.current?.appendChild(track.attach());
      });
      r.on(RoomEvent.Disconnected, () => setStatus("ended"));
      // Browsers (Safari especially) hold back audio that starts after the click; offer a button then.
      r.on(RoomEvent.AudioPlaybackStatusChanged, () => setAudioBlocked(!r.canPlaybackAudio));
      r.on(RoomEvent.ParticipantConnected, (p) => {
        if (p.isAgent) { setAgentJoined(true); setProblem(null); }
      });
      await r.connect(info.url, info.token);
      await r.startAudio().catch(() => undefined);
      setAudioBlocked(!r.canPlaybackAudio);
      if ([...r.remoteParticipants.values()].some((p) => p.isAgent)) setAgentJoined(true);
      try {
        await r.localParticipant.setMicrophoneEnabled(true);
      } catch {
        setProblem("Microphone access was blocked. Allow the microphone for this site and start the call again.");
      }
      setRoom(r); setRoomName(info.room); setStatus("connected");
    } catch (e) {
      setStatus("idle");
      setError(e instanceof Error && e.message.includes("could not establish")
        ? new Error("Could not reach LiveKit. Is the livekit and voice-runtime service running?") : e);
    }
  };

  const end = async () => {
    await room?.disconnect();
    setRoom(null); setStatus("ended");
  };

  const lastUser = [...(detail?.messages ?? [])].reverse().find((m) => m.role === "user");
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2"><Radio className="h-4 w-4" /> Real-time call (WebRTC)
            <span className={cn("text-xs font-normal", status === "connected" ? "text-emerald-600" : "text-muted-foreground")}>{status}</span></CardTitle>
          {status === "connected" ? <Button variant="destructive" onClick={end}><PhoneOff className="h-4 w-4" /> End call</Button>
            : <Button onClick={start} disabled={status === "connecting"}>Start real-time call</Button>}
        </CardHeader>
        <CardContent className="space-y-3">
          <Alert variant="info">Speak naturally - you can interrupt the agent at any time. Uses the same runtime as phone calls.</Alert>
          {status === "connected" && !problem && (
            <p className="text-sm text-muted-foreground">
              {!agentJoined ? "Connected. Waiting for the AI agent to join…" : !callId ? "Agent joined. Starting the call…" : "Agent is listening - say something."}
            </p>
          )}
          {problem && <Alert variant="warning">{problem}</Alert>}
          {status === "connected" && audioBlocked && (
            <Button variant="outline" className="w-full"
              onClick={() => room?.startAudio().then(() => setAudioBlocked(!room.canPlaybackAudio)).catch(() => undefined)}>
              <Volume2 className="h-4 w-4" /> Your browser paused the sound - click to hear the agent
            </Button>
          )}
          <ErrorBox error={error} />
          <div className="h-[380px] space-y-2 overflow-y-auto rounded-lg bg-muted/40 p-3">
            {detail?.messages.map((m) => (
              <div key={m.seq} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div dir="auto" className={cn("max-w-[80%] rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-primary text-primary-foreground" : "border bg-card")}>{m.content}</div>
              </div>
            ))}
          </div>
          <div ref={audioHost} className="hidden" />
          {callId && <Link href={`/calls/${callId}`} className="text-sm text-primary hover:underline">Open full call details →</Link>}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle className="text-sm">Live debugging</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          {!detail && <p className="text-muted-foreground">
            {status !== "connected" ? "Start a real-time call to see live data." : !agentJoined ? "Waiting for the AI agent to join…" : "Waiting for the call to start…"}
          </p>}
          {detail && (<>
            <div>Language: <b>{detail.call.language ?? "-"}</b> · Dialect: <b>{dialectName(lastUser?.dialect ?? detail.call.dialect)}</b></div>
            <div>Intent: <b>{detail.call.intent ?? "-"}</b> · Avg response: {detail.call.metrics.avg_turn_latency_ms ?? "-"} ms</div>
            {detail.workflow && <div className="flex flex-wrap gap-1">{detail.workflow.path.slice(-10).map((p, i) => <Badge key={i} variant="outline">{p}</Badge>)}</div>}
            {detail.tool_executions.slice(-6).map((t) => (
              <div key={t.id} className="flex justify-between rounded border p-1.5 font-mono text-xs"><span>{t.tool_name}</span>
                <Badge variant={t.status === "succeeded" ? "success" : "warning"}>{t.status}</Badge></div>
            ))}
          </>)}
        </CardContent>
      </Card>
    </div>
  );
}
