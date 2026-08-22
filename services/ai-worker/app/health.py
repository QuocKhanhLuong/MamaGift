"""Internal health endpoint for the AI worker."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from mamagift_contracts.worker import WorkerCapabilities, WorkerHealth

from .auth import verify_bearer_token
from .settings import WorkerSettings, get_worker_settings

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.get("/health", response_model=WorkerHealth)
async def get_health(
    _token: Annotated[str, Depends(verify_bearer_token)],
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> WorkerHealth:
    """Return worker status, capabilities, and loaded models."""
    models: dict[str, str] = {}
    if settings.model_llm:
        models["llm"] = settings.model_llm
    if settings.model_embedding:
        models["embedding"] = settings.model_embedding
    if settings.model_ocr:
        models["ocr"] = settings.model_ocr

    return WorkerHealth(
        status=settings.status,
        worker_version=settings.worker_version,
        capabilities=WorkerCapabilities(
            parse=settings.capability_parse,
            embed=settings.capability_embed,
            rerank=settings.capability_rerank,
            llm=settings.capability_llm,
        ),
        models=models,
    )
