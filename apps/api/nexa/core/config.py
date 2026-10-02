"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Nexa Voice Agents"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://nexa:nexa@localhost:5432/nexa"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12
    # Fernet key (urlsafe base64, 32 bytes). Used to encrypt integration credentials.
    encryption_key: str = "Wm9vX2RldmVsb3BtZW50X2tleV9kb19ub3RfdXNlXzE="
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 20

    # --- AI providers ------------------------------------------------------
    local_ai: bool = True
    llm_provider: Literal["local", "openai_compatible", "cloud", "custom", "scripted"] = "local"
    llm_base_url: str = "http://llm:8000/v1"
    llm_model: str = "Qwen/Qwen3-8B"
    llm_api_key: str = "not-needed"
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.3
    llm_max_tokens: int = 400
    # Qwen3 reasoning models emit <think> blocks; disable for voice latency.
    llm_disable_thinking: bool = True

    stt_provider: Literal["whisper", "openai_compatible", "none"] = "whisper"
    stt_base_url: str = "http://stt:8001/v1"
    stt_model: str = "large-v3"

    tts_provider: Literal["piper", "none"] = "piper"
    tts_base_url: str = "http://tts:8002"

    embedding_provider: Literal["hashing", "openai_compatible"] = "hashing"
    embedding_base_url: str = "http://embeddings:8003/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 384

    # --- Telephony ----------------------------------------------------------
    sip_provider: Literal["livekit", "none"] = "livekit"
    livekit_url: str = "ws://livekit:7880"
    livekit_api_url: str = "http://livekit:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret_devsecret_devsecret_devsecret"

    # --- Integrations -------------------------------------------------------
    # Block REST/DB integrations that resolve to private networks (SSRF protection).
    allow_private_network_integrations: bool = False
    integration_timeout_seconds: float = 10.0
    # Bundled demo clinic database (Doctor Appointment template, development only).
    demo_clinic_database_url: str = "postgresql://clinic_agent:clinic_agent@postgres:5432/clinic_demo"

    # Run background jobs (document ingestion) in-process instead of via the Redis queue/worker.
    jobs_inline: bool = False
    max_upload_bytes: int = 20_000_000

    max_agent_tool_iterations: int = 4
    handoff_failure_threshold: int = 2

    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
