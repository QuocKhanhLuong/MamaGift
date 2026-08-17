"""Environment-backed API settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./mamagift.db"
    ai_worker_base_url: str = "http://localhost:8090"
    ai_worker_token: str = "local-fake-worker-token"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Phase 2 ingestion.
    storage_root: str = "./var/storage"
    max_upload_bytes: int = 50 * 1024 * 1024
    # Path to the parser strategy configuration. Unset means ADR-001 is undecided and
    # the pipeline may only run the baseline parser outside production.
    parser_strategy_path: str | None = None
    job_lease_seconds: int = 300
    job_max_attempts: int = 3
    job_retry_backoff_seconds: int = 30
    page_preview_dpi: int = 110

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
