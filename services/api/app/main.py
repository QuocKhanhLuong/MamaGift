"""The MamaGift API application."""

from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .errors import ApiError, api_error_handler
from .routers import documents
from .settings import get_settings


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["api"] = "api"
    version: str


settings = get_settings()
app = FastAPI(title="MamaGift API", version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(documents.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Return a dependency-free API liveness response."""

    return HealthResponse(version=settings.app_version)
