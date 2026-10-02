# Real-time voice runtime (LiveKit Agents worker). Build context: repository root.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/nexa apps/api/nexa
RUN pip install ./apps/api
COPY services/voice-runtime/requirements.txt services/voice-runtime/requirements.txt
RUN pip install -r services/voice-runtime/requirements.txt
COPY services/voice-runtime/nexa_voice services/voice-runtime/nexa_voice
WORKDIR /app/services/voice-runtime
# Pre-download the Silero VAD model into the image.
RUN python -m nexa_voice.main download-files || true
CMD ["python", "-m", "nexa_voice.main", "start"]
