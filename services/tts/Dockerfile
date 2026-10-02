# Piper (CPU) by default. For natural neural voices with cloning (GPU recommended):
#   --build-arg NEURAL=true  (and a CUDA base, e.g. --build-arg BASE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime)
ARG BASE=python:3.11-slim
FROM ${BASE}
ARG NEURAL=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-neural.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$NEURAL" = "true" ]; then pip install --no-cache-dir -r requirements-neural.txt; fi
COPY app.py neural.py ./
ENV PIPER_VOICE_DIR=/models/piper NEURAL_VOICE_DIR=/models/neural-voices HF_HOME=/models/hf
EXPOSE 8002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
