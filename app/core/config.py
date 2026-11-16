from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Pydantic v2 style (replaces the v1 inner `class Config`).
    # env_file: read values from .env in the project root.
    # extra="ignore": .env also holds POSTGRES_* keys for docker-compose;
    # without this, unknown keys would stop the app from starting.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    # Signs every login token. An empty or short secret lets anyone forge a
    # token, so the app refuses to start without 32+ characters.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Uploads
    storage_dir: str = "storage"          # originals/ and clean/ live under here
    max_files_per_batch: int = 50
    max_file_mb: int = 15                 # a modern phone photo is 3-8 MB
    queue_name: str = "catalog:queue"     # Redis list the worker reads from

    # Background removal model (see experiments/2026-11-14_rembg_models/results.md)
    # Concept: CONFIG OVER CODE. Switching models = edit .env, no code change.
    # Example: REMBG_MODEL=birefnet-general-lite in .env -> cleaner, ~6x slower
    rembg_model: str = "isnet-general-use"

    # --- AI provider (pluggable) ---
    # Concept: PLUGGABLE PROVIDER. One setting picks who describes the photo.
    # Example: AI_PROVIDER=ollama (free, local) for daily work,
    #          AI_PROVIDER=claude for the evaluation and demo.
    ai_provider: Literal["ollama", "claude"] = "ollama"

    # Ollama: runs on this Mac, no key, no cost
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5vl:7b"

    # Claude: only needed when ai_provider = "claude"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-haiku-5-5"   # compared with claude-opus-5-5 at evaluation
    claude_max_retries: int = 4              # the SDK retries 429/5xx itself, with backoff

    # Concept: CROSS-FIELD VALIDATION. The key is optional in general, but
    # REQUIRED when Claude is chosen, so the app fails at startup, not on photo 1.
    @model_validator(mode="after")
    def claude_needs_a_key(self):
        if self.ai_provider == "claude" and not self.anthropic_api_key:
            raise ValueError("AI_PROVIDER=claude needs ANTHROPIC_API_KEY in .env")
        return self

settings = Settings()
