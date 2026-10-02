# Natural voices and accurate recognition

Voice and recognition engines are chosen without code: the **voice per agent** (Agent → General → Voice),
the **recognition engine per deployment** (`STT_PROVIDER`). Everything sits behind the `TTSProvider` /
`STTProvider` interfaces, so engines can be swapped without touching the runtime.

## Voices (how the agent sounds)

| Provider | Where it runs | Sound | Dialects | Your own voice | Needs |
|---|---|---|---|---|---|
| **Standard** (Piper) | your servers, CPU | clear, synthetic | one Arabic voice | - | nothing (default) |
| **Natural** (Chatterbox Multilingual, MIT) | your servers | natural, human-like | Arabic + English | yes - clone from a 10-30 s recording | NVIDIA GPU (`docker compose --profile neural up`) |
| **ElevenLabs** | cloud | most human-like | Arabic + English, very expressive | yes - in your ElevenLabs account | `ELEVENLABS_API_KEY` |
| **Azure Neural** | cloud | natural | native voice **per dialect** (Saudi, Gulf, Kuwaiti, Qatari, Bahraini, Omani, Iraqi, Levantine, Egyptian, Yemeni, Libyan, Tunisian, Algerian, Moroccan) | - | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |

* **Answer in the caller's dialect** (Azure): the agent detects the caller's dialect and replies with a native voice
  of that dialect - an Egyptian caller hears an Egyptian voice, a Kuwaiti caller a Kuwaiti one.
* **Your own voices** - the **Voices** page (sidebar): upload a recording, give it any name (Arabic or English), choose
  the engine (Natural self-hosted or ElevenLabs) and confirm you have the speaker's permission. The voice appears in the
  list - play the original recording, hear the clone, rename or delete it - and in every agent's voice picker as
  "<name> (your voice)". Deleting is blocked while an agent's draft or live version still uses the voice. The original
  recording is stored with the voice, so a self-hosted clone is re-created automatically if the voice service loses it.
  Use at least 4 seconds of one clear speaker; 10-30 seconds sounds closest.
* **Natural pauses**: when checking information takes a moment, the agent says "لحظة من فضلك" / "One moment" instead
  of going silent - like a receptionist would.
* **Preview**: every voice can be played from the settings page before you save.

Responsible use: only clone voices you have explicit permission to use. Chatterbox embeds an inaudible watermark in
generated audio. Consider telling callers they are speaking with an AI assistant where the law requires it
(Agent → Privacy → consent message).

## Recognition (how well the agent understands)

| Engine | Where | Accuracy on Arabic | Speed | Setting |
|---|---|---|---|---|
| Whisper **large-v3** | your GPU | best of the local models | real-time on a GPU | `WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16` |
| Whisper **large-v3-turbo** | your GPU / strong CPU | close to large-v3 | ~3x faster | `WHISPER_MODEL=large-v3-turbo` |
| Whisper small | CPU | noticeably lower | fast | default for laptops only |
| ElevenLabs Scribe | cloud | excellent incl. dialects and Arabic/English mixing | fast | `STT_PROVIDER=elevenlabs` |
| Azure Speech | cloud | good; dialect-specific locale | fast | `STT_PROVIDER=azure` |

**Vocabulary** (Agent → Languages → *Words callers will say*): list doctor names, specialties, products and places.
They are passed to the recognizer (Whisper hotwords / ElevenLabs keyterms) together with the business name, which
fixes most errors on names - the most common source of misunderstanding on calls.

The browser test console records 16 kHz WAV; phone calls use LiveKit's audio pipeline with VAD and turn detection.

## Measured in development (CPU, synthetic test speech)

Same Arabic sentence, transcribed back by Whisper large-v3 to check intelligibility:

| Voice | Transcription |
|---|---|
| Natural (Chatterbox) | أهلاً وسهلاً، معك عيادة الشفاء؟ عندي موعد يوم الأحد الساعة ستة ونص مساءً مع الدكتورة سارة يناسبك؟ - correct |
| Standard (Piper) | … مع الدكتورة **سرة** **يناسبه** - errors on the name and the last word |

A cloned voice moved the speaking pitch from 137 Hz (default voice) to 179 Hz toward the reference speaker (197 Hz)
and remained fully intelligible. On CPU, natural synthesis takes ~1-2 minutes per sentence - it requires a GPU for
live calls (roughly real time on a modern NVIDIA GPU).

Recognition word error rate on six Arabic test sentences (dialects, doctor names, a phone number, Arabic/English
mixing), CPU int8, synthetic test speech - indicative only; measure on recordings of your real callers:

| Model | Without vocabulary | With vocabulary |
|---|---|---|
| Whisper small (old default) | 34.1% | - |
| Whisper large-v3-turbo | 18.8% | 13.9% |
| Whisper large-v3 | 28.8% | **9.0%** |

Recommendation: Whisper **large-v3 on a GPU with the agent's vocabulary filled in**, or ElevenLabs Scribe if you
prefer a cloud service. Whisper small is only meant for trying the platform on a laptop.
