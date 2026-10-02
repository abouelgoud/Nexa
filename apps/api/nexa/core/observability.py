"""Structured logging, Prometheus metrics and optional OpenTelemetry tracing."""

from __future__ import annotations

import json
import logging
import sys
import time

from prometheus_client import Counter, Histogram

LATENCY_BUCKETS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 13)

STT_LATENCY = Histogram("nexa_stt_latency_seconds", "Speech-to-text latency", buckets=LATENCY_BUCKETS)
TTS_LATENCY = Histogram("nexa_tts_latency_seconds", "Text-to-speech latency", buckets=LATENCY_BUCKETS)
LLM_LATENCY = Histogram("nexa_llm_latency_seconds", "LLM total latency", ["purpose"], buckets=LATENCY_BUCKETS)
LLM_TTFT = Histogram("nexa_llm_ttft_seconds", "LLM time to first token", buckets=LATENCY_BUCKETS)
TURN_LATENCY = Histogram("nexa_turn_latency_seconds", "End-to-end turn latency (text in -> reply)",
                         ["mode"], buckets=LATENCY_BUCKETS)
TOOL_LATENCY = Histogram("nexa_tool_latency_seconds", "Tool execution latency", ["category", "status"],
                         buckets=LATENCY_BUCKETS)
TOOL_FAILURES = Counter("nexa_tool_failures_total", "Failed tool executions", ["tool", "code"])
CALLS = Counter("nexa_calls_total", "Calls started", ["channel"])
CALL_FAILURES = Counter("nexa_call_failures_total", "Calls that ended with an error", ["channel"])
API_ERRORS = Counter("nexa_api_errors_total", "API error responses", ["code"])


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)), "level": record.levelname,
                   "logger": record.name, "msg": record.getMessage()}
        for key in ("tenant_id", "call_id", "request_id", "path", "status", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def setup_tracing(app, endpoint: str | None, service_name: str = "nexa-api") -> None:
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
