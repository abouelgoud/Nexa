# Piper (CPU) by default. For natural neural voices with cloning:
#   --build-arg NEURAL=true       Chatterbox Multilingual (MIT)
#   --build-arg NEURAL=omnivoice  OmniVoice (weights are non-commercial), run with NEURAL_MODEL=omnivoice
# with a CUDA base (--build-arg BASE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime) on NVIDIA, or the default
# base on a CPU-only Linux server. On a Mac, run the service natively instead (scripts/voice-mac.sh).
ARG BASE=python:3.11-slim
FROM ${BASE}
ARG NEURAL=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-neural.txt requirements-omnivoice.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$NEURAL" = "true" ]; then pip install --no-cache-dir -r requirements-neural.txt; fi && \
    if [ "$NEURAL" = "omnivoice" ]; then pip install --no-cache-dir -r requirements-omnivoice.txt; fi
COPY app.py neural.py ./
ENV PIPER_VOICE_DIR=/models/piper NEURAL_VOICE_DIR=/models/neural-voices HF_HOME=/models/hf
EXPOSE 8002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
