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
    status: Literal["online", "offline", "degraded"] = "offline"
    timeout_seconds: float = 30.0

    # Capabilities (contract-only worker defaults to False)
    capability_parse: bool = False
    capability_embed: bool = False
    capability_rerank: bool = False
    capability_llm: bool = False

    # Model identifiers (empty by default when no backing model is loaded)
    model_llm: str = ""
    model_embedding: str = ""
    model_ocr: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="forbid",
    )


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
