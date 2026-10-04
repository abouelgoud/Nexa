# Real-time calls

Phone calls and the browser "Real-time (WebRTC)" test use the same pipeline: LiveKit carries the audio, the
`voice-runtime` worker runs each call (as a thread in one process), and every turn goes through Nexa's
`ConversationRuntime` - the same code as the text test console.

| Feature | How |
|---|---|
| Streaming | Replies are spoken sentence by sentence. Natural (self-hosted) voices go further: each sentence is rendered in short phrases (the first one at most 4 words) and every phrase is played as soon as it is ready. |
| Low latency | Fixed lines - greeting, workflow questions, "لحظة من فضلك" - are rendered ahead of time in the agent's natural voice whenever the agent or its workflow is saved, and kept on disk by the voice service, so they play instantly. If checking takes longer than 0.9 s the agent says "one moment" instead of going silent. |
| Interruption / barge-in | Voice activity detection: the caller can talk over the agent at any time and it stops speaking. Speech during the agent's first seconds is kept, not dropped. |
| Conversation state | Per call: language and dialect, workflow position and collected variables, confirmations. |
| Tool execution | Workflow tool nodes and agent-mode tool calls, permission-checked, logged per call. Writes need the caller's confirmation. |
| Human handoff | Workflow `transfer` node or the agent's transfer action: on phone calls a SIP transfer to the configured number after the agent finishes speaking. |
| Call recording | Agent → Privacy → Record calls. Stereo OGG (caller left, agent right; only what was actually heard), stored by the worker in the recordings folder and playable on the call page. Deleted by the retention job with the transcript. |
| Real-time transcription | The worker publishes both sides' words live over LiveKit (`lk.transcription`); the test page shows them as they happen - the agent's words in sync with its voice, the caller's as soon as they are recognised. |

## What decides the speed

Per turn: end of the caller's speech is detected (~0.4 s of silence) → recognition → reply → voice. The call
worker logs a `timing:` line for each stage, and the call page shows "recognized in" / "answered in" per turn.

* **Recognition** (Whisper) is usually the slowest step without a GPU. On a Mac run it on the Apple GPU:
  `scripts/stt-mac.sh` (Docker) or `scripts/dev-mac.sh` (native).
* **Natural voices** render on the GPU; on a CPU they are far too slow for calls. Pre-rendered lines are instant on
  any machine; new sentences (times, names) take as long as their first short phrase. For the fastest natural
  voice, use ElevenLabs (cloud).
* **Standard voice (Piper)** is the fastest local voice (a few hundred ms per sentence on a CPU).

Measured on a 4-core cloud CPU (no GPU) with the natural voice, for "تمام، تم حجز موعدك مع الدكتورة سارة. هل تحتاج
أي شي ثاني؟": whole reply before any sound 49.7 s; with phrase streaming, first sound after 19.9 s; a pre-rendered
phrase 3 ms. A GPU makes the rendering many times faster; the pre-rendered lines stay instant.
