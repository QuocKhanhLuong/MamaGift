"""Environment-backed AI worker settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    worker_env: str = "development"
    worker_version: str = "0.4.0"
    worker_host: str = "0.0.0.0"
    worker_port: int = 8090
    auth_token: str = "local-fake-worker-token"
    status: Literal["online", "offline", "degraded"] = "online"
    timeout_seconds: float = 30.0

    # Capabilities
    capability_parse: bool = True
    capability_embed: bool = True
    capability_rerank: bool = False
    capability_llm: bool = True

    # Model identifiers
    model_llm: str = "qwen2.5-7b-instruct"
    model_embedding: str = "bge-m3"
    model_ocr: str = "pp-structure-v3"

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
