# CPU image by default. For NVIDIA GPUs build with:
#   --build-arg BASE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04  and set WHISPER_DEVICE=cuda
ARG BASE=python:3.11-slim
FROM ${BASE}
RUN if ! command -v python3 >/dev/null; then apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*; fi
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV WHISPER_MODEL_DIR=/models/whisper
EXPOSE 8001
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
