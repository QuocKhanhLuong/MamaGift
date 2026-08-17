"""Document ingestion and retrieval endpoints (`/api/v1/documents`).

The API is application-oriented: parser and provider details are metadata on a parse
run, never something the client has to understand
(`docs/08_API_AND_DATA_CONTRACTS.md` sections 1, 11 and 12).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mamagift_docpipe import ParserError, render_page_png

from .. import errors, ingestion
from ..db import get_session
from ..dependencies import get_storage
from ..models import Document, ParseRun
from ..schemas import (
    CanonicalResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentSummary,
    JobSummary,
    ParseRunSummary,
    ReprocessResponse,
    UploadResponse,
)
from ..settings import Settings, get_settings
from ..storage import ObjectStorage, StorageError

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

SessionDep = Annotated[Session, Depends(get_session)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _load_document(session: Session, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise errors.ApiError(
            errors.NOT_FOUND,
            "document not found",
            status_code=404,
            details={"document_id": document_id},
        )
    return document


@router.post("", response_model=UploadResponse, status_code=202)
async def upload_document(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    response: Response,
    file: Annotated[UploadFile, File(description="The original PDF")],
) -> UploadResponse:
    """Store the original bytes immutably and queue a parse job."""
    data = await file.read()
    result = ingestion.create_document(
        session,
        storage,
        settings,
        filename=file.filename or "document.pdf",
        content_type=file.content_type or "",
        data=data,
    )
    if result.duplicate:
        # The bytes already exist; nothing new was created.
        response.status_code = 200
    return UploadResponse(
        document=DocumentSummary.from_model(result.document),
        job=JobSummary.from_model(result.job),
        duplicate_of_existing=result.duplicate,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    session: SessionDep,
    status: Annotated[str | None, Query(description="Filter by document status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    filters = [Document.status == status] if status else []

    total = session.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    rows = session.scalars(
        select(Document)
        .where(*filters)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return DocumentListResponse(
        items=[DocumentSummary.from_model(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(session: SessionDep, document_id: str) -> DocumentDetailResponse:
    document = _load_document(session, document_id)
    runs = session.scalars(
        select(ParseRun)
        .where(ParseRun.document_id == document.id)
        .order_by(ParseRun.version.desc())
    ).all()
    return DocumentDetailResponse(
        document=DocumentSummary.from_model(document),
        parse_runs=[ParseRunSummary.from_model(run) for run in runs],
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(session: SessionDep, document_id: str) -> DocumentStatusResponse:
    document = _load_document(session, document_id)
    job = ingestion.latest_job(session, document.id)
    current = (
        session.get(ParseRun, document.current_parse_run_id)
        if document.current_parse_run_id
        else None
    )
    return DocumentStatusResponse(
        document=DocumentSummary.from_model(document),
        latest_job=None if job is None else JobSummary.from_model(job),
        current_parse_run=None if current is None else ParseRunSummary.from_model(current),
    )


@router.get("/{document_id}/canonical", response_model=CanonicalResponse)
def get_canonical(
    session: SessionDep,
    document_id: str,
    version: Annotated[int | None, Query(ge=1, description="Parse run version")] = None,
) -> CanonicalResponse:
    """Return the current canonical document, or a specific historical version."""
    document = _load_document(session, document_id)

    if version is not None:
        run = session.scalar(
            select(ParseRun).where(ParseRun.document_id == document.id, ParseRun.version == version)
        )
    elif document.current_parse_run_id:
        run = session.get(ParseRun, document.current_parse_run_id)
    else:
        run = None

    if run is None:
        raise errors.ApiError(
            errors.NOT_FOUND,
            "no canonical document is available yet",
            status_code=404,
            details={"document_id": document_id, "status": document.status},
        )

    canonical: dict[str, Any] = run.canonical
    return CanonicalResponse(parse_run=ParseRunSummary.from_model(run), canonical=canonical)


@router.get("/{document_id}/file")
def get_original_file(
    session: SessionDep,
    storage: StorageDep,
    document_id: str,
) -> FileResponse:
    """Serve the immutable original upload for verification."""
    document = _load_document(session, document_id)
    try:
        path = storage.local_path(document.storage_uri)
    except StorageError as exc:
        raise errors.ApiError(
            errors.STORAGE_FAILURE, "the original file is unavailable", status_code=500
        ) from exc

    if not path.is_file():
        raise errors.ApiError(
            errors.STORAGE_FAILURE, "the original file is unavailable", status_code=500
        )

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{document_id}/pages/{page}/preview")
def get_page_preview(
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    document_id: str,
    page: int,
) -> Response:
    """Render one page of the original document as a PNG."""
    document = _load_document(session, document_id)
    try:
        png = render_page_png(
            storage.local_path(document.storage_uri),
            page_number=page,
            dpi=settings.page_preview_dpi,
        )
    except ParserError as exc:
        payload = exc.to_dict()
        status_code = 404 if payload["code"] == "unsupported_input" else 400
        raise errors.ApiError(
            payload["code"],
            payload["message"],
            status_code=status_code,
            retryable=payload["retryable"],
        ) from exc
    except StorageError as exc:
        raise errors.ApiError(
            errors.STORAGE_FAILURE, "the original file is unavailable", status_code=500
        ) from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{document_id}/reprocess", response_model=ReprocessResponse, status_code=202)
def reprocess_document(
    session: SessionDep,
    settings: SettingsDep,
    document_id: str,
) -> ReprocessResponse:
    """Queue a new parse run. Existing runs are kept and never overwritten."""
    document = _load_document(session, document_id)
    job = ingestion.reprocess_document(session, document, settings)
    return ReprocessResponse(
        document=DocumentSummary.from_model(document),
        job=JobSummary.from_model(job),
    )
