# API + worker image (they share the `nexa` package). Build context: repository root.
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/nexa apps/api/nexa
RUN pip install ./apps/api
COPY apps/api/alembic apps/api/alembic
COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/worker/nexa_worker apps/worker/nexa_worker
ENV PYTHONPATH=/app/apps/worker
WORKDIR /app/apps/api
RUN useradd --create-home --uid 10001 nexa
USER nexa
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn nexa.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
