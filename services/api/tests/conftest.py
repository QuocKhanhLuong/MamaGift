"""Shared fixtures for the API tests.

Every test gets an empty database created by the real migrations, so the schema under
test is the schema that ships (`docs/09_CODEX_EXECUTION.md` section 10).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.db import get_session
from app.dependencies import get_storage
from app.main import app
from app.settings import Settings, get_settings
from app.storage import LocalObjectStorage

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PDF = REPO_ROOT / "benchmarks" / "parser" / "fixtures" / "cong_van_born_digital.pdf"
DECISION_PDF = REPO_ROOT / "benchmarks" / "parser" / "fixtures" / "quyet_dinh_dieu_khoan.pdf"
ENCRYPTED_PDF = REPO_ROOT / "benchmarks" / "parser" / "fixtures" / "tai_lieu_ma_hoa.pdf"
INVALID_PDF = REPO_ROOT / "benchmarks" / "parser" / "fixtures" / "tep_khong_hop_le.pdf"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        storage_root=str(tmp_path / "storage"),
        max_upload_bytes=2 * 1024 * 1024,
        parser_strategy_path=None,
        job_lease_seconds=60,
        job_max_attempts=3,
        job_retry_backoff_seconds=0,
    )


@pytest.fixture
def engine(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    config = Config(str(REPO_ROOT / "services" / "api" / "alembic.ini"))
    command.upgrade(config, "head")

    created = create_engine(settings.database_url, future=True)
    try:
        yield created
    finally:
        created.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as active:
        yield active


@pytest.fixture
def storage(settings: Settings) -> LocalObjectStorage:
    return LocalObjectStorage(settings.storage_root)


@pytest.fixture
def client(
    settings: Settings,
    session_factory: sessionmaker[Session],
    storage: LocalObjectStorage,
) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with session_factory() as active:
            yield active

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def pdf_bytes() -> bytes:
    return FIXTURE_PDF.read_bytes()


@pytest.fixture
def upload() -> Callable[..., Response]:
    """Post a PDF upload; the default filename and content type are the happy path."""

    def _upload(
        client: TestClient,
        data: bytes,
        filename: str = "cong-van.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        return client.post(
            "/api/v1/documents",
            files={"file": (filename, data, content_type)},
        )

    return _upload


@pytest.fixture
def fixture_paths() -> dict[str, Path]:
    return {
        "cong_van": FIXTURE_PDF,
        "quyet_dinh": DECISION_PDF,
        "encrypted": ENCRYPTED_PDF,
        "invalid": INVALID_PDF,
    }
