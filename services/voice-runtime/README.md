# Voice runtime (real-time)

A [LiveKit Agents](https://docs.livekit.io/agents/) worker named `nexa-voice`.

- **Phone**: carrier SIP trunk → LiveKit SIP → dispatch rule (created by `POST /phone-numbers`) → this worker.
- **Browser**: `POST /test/realtime` returns a LiveKit token whose room config dispatches this worker.

LiveKit provides audio transport, Silero VAD, end-of-turn detection and barge-in (the caller can
interrupt; playback stops immediately). Every turn is handled by Nexa's `ConversationRuntime`
(`apps/api/nexa/runtime/session.py`) - the same code used by the browser text/push-to-talk tests -
so language/dialect detection, workflows, tools, confirmation rules, logging and usage are identical
for phone and web.

STT/TTS run through Nexa's provider interfaces (`NexaSTT`, `NexaTTS` adapters in `nexa_voice/plugins.py`),
so swapping Whisper/Piper for another provider needs no change here. Transfers use SIP REFER via
`SIPProvider.transfer` after the agent finishes speaking.

```bash
python -m nexa_voice.main dev      # local development against LIVEKIT_URL
python -m nexa_voice.main start    # production
```
