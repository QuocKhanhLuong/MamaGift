"""Ingestion service layer: upload, jobs, parse runs and versioning.

Ordering matters and is enforced here: the original bytes are durable *before* a job
exists, so no worker can ever lease a job whose input is missing. Reprocessing adds a
new parse run and never rewrites an old one, per the data rule in
`docs/09_CODEX_EXECUTION.md` section 8.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Select, func, or_, select, update
from sqlalchemy.orm import Session

from mamagift_docpipe import (
    CanonicalDocument,
    ParserError,
    ParserErrorCode,
    ParserStrategy,
    load_strategy,
    run_ingestion,
    validate_pdf_bytes,
)

from . import errors
from .models import Document, Job, ParseRun
from .settings import Settings
from .state_machine import (
    TERMINAL_JOB_STATUSES,
    DocumentStatus,
    JobStatus,
    assert_document_transition,
    assert_job_transition,
)
from .storage import ObjectStorage, StorageError, checksum_of

PARSE_JOB_KIND = "parse"

ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})

# Parser failures that will fail identically on every retry.
TERMINAL_PARSER_CODES = frozenset(
    {
        ParserErrorCode.ENCRYPTED_PDF,
        ParserErrorCode.INVALID_PDF,
        ParserErrorCode.UNSUPPORTED_INPUT,
        ParserErrorCode.NORMALIZATION_FAILURE,
        ParserErrorCode.PARSER_STRATEGY_UNDECIDED,
    }
)

# Parser failures that mean the document itself cannot be supported.
UNSUPPORTED_PARSER_CODES = frozenset({ParserErrorCode.ENCRYPTED_PDF, ParserErrorCode.INVALID_PDF})


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; compare everything in UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


@dataclass
class UploadResult:
    document: Document
    job: Job
    duplicate: bool


def set_document_status(document: Document, target: DocumentStatus) -> None:
    current = DocumentStatus(document.status)
    if current == target:
        return
    assert_document_transition(current, target)
    document.status = target.value
    document.updated_at = _now()


def set_job_status(job: Job, target: JobStatus) -> None:
    current = JobStatus(job.status)
    assert_job_transition(current, target)
    job.status = target.value
    job.updated_at = _now()


# ------------------------------------------------------------------------- upload


def _validate_upload(filename: str, content_type: str, data: bytes, settings: Settings) -> None:
    if not filename.lower().endswith(".pdf"):
        raise errors.ApiError(
            errors.UNSUPPORTED_MEDIA_TYPE,
            "only .pdf files are accepted",
            status_code=415,
            details={"filename": filename},
        )
    if content_type.split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
        raise errors.ApiError(
            errors.UNSUPPORTED_MEDIA_TYPE,
            "content type must be application/pdf",
            status_code=415,
            details={"content_type": content_type},
        )
    if len(data) == 0:
        raise errors.ApiError(errors.INVALID_PDF, "uploaded file is empty", status_code=400)
    if len(data) > settings.max_upload_bytes:
        raise errors.ApiError(
            errors.FILE_TOO_LARGE,
            f"file exceeds the {settings.max_upload_bytes} byte limit",
            status_code=413,
            details={"byte_size": len(data), "limit": settings.max_upload_bytes},
        )

    verdict = validate_pdf_bytes(data)
    if verdict.encrypted:
        raise errors.ApiError(
            errors.ENCRYPTED_PDF,
            "the document is password protected and cannot be processed",
            status_code=400,
        )
    if not verdict.is_pdf:
        raise errors.ApiError(
            errors.INVALID_PDF,
            "the file is not a readable PDF",
            status_code=400,
            details={"detail": verdict.detail},
        )


def create_document(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    filename: str,
    content_type: str,
    data: bytes,
) -> UploadResult:
    """Validate, store immutably, persist the row, then enqueue the parse job."""
    _validate_upload(filename, content_type, data, settings)

    checksum = checksum_of(data)
    existing = session.scalar(select(Document).where(Document.checksum_sha256 == checksum))
    if existing is not None:
        # Duplicate byte-identical upload: the original is already durable, so the
        # existing document is returned instead of creating a second one.
        job = latest_job(session, existing.id)
        if job is None:
            job = enqueue_parse_job(
                session,
                existing,
                reason="duplicate_upload",
                max_attempts=settings.job_max_attempts,
            )
            session.commit()
        return UploadResult(document=existing, job=job, duplicate=True)

    try:
        storage_uri = storage.put_original(checksum, data)
    except StorageError as exc:
        raise errors.ApiError(
            errors.STORAGE_FAILURE,
            "the original document could not be stored",
            status_code=500,
            retryable=True,
        ) from exc

    document = Document(
        id=new_id("doc"),
        filename=filename,
        content_type="application/pdf",
        byte_size=len(data),
        checksum_sha256=checksum,
        storage_uri=storage_uri,
        status=DocumentStatus.UPLOADED.value,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(document)
    session.flush()

    job = enqueue_parse_job(
        session, document, reason="upload", max_attempts=settings.job_max_attempts
    )
    session.commit()
    return UploadResult(document=document, job=job, duplicate=False)


# --------------------------------------------------------------------------- jobs


def next_parse_run_version(session: Session, document_id: str) -> int:
    current_max = session.scalar(
        select(func.max(ParseRun.version)).where(ParseRun.document_id == document_id)
    )
    return int(current_max or 0) + 1


def enqueue_parse_job(
    session: Session,
    document: Document,
    reason: str,
    max_attempts: int = 3,
) -> Job:
    """Queue a parse job idempotently.

    The idempotency key is derived from the document and the parse-run version the job
    would produce, so re-queueing for the same target version returns the same job
    instead of creating a duplicate. A job that already reached a terminal state is
    never handed back: it can no longer run, so reusing it would turn `/reprocess`
    into a silent no-op. The key then carries a generation ordinal, which keeps
    `uq_jobs_idempotency_key` satisfied without deleting the failed job's history.
    """
    target_version = next_parse_run_version(session, document.id)
    base_key = f"{document.id}:{PARSE_JOB_KIND}:v{target_version}"

    idempotency_key = base_key
    generation = 0
    while True:
        existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing is None:
            break
        if JobStatus(existing.status) not in TERMINAL_JOB_STATUSES:
            return existing
        generation += 1
        idempotency_key = f"{base_key}#{generation}"

    job = Job(
        id=new_id("job"),
        document_id=document.id,
        kind=PARSE_JOB_KIND,
        status=JobStatus.QUEUED.value,
        attempt=0,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        available_at=_now(),
        error={"reason": reason} if reason else None,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(job)
    session.flush()

    if DocumentStatus(document.status) != DocumentStatus.QUEUED_FOR_PARSE:
        set_document_status(document, DocumentStatus.QUEUED_FOR_PARSE)
    return job


def latest_job(session: Session, document_id: str) -> Job | None:
    return session.scalar(
        select(Job)
        .where(Job.document_id == document_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )


EXPIRABLE_JOB_STATUSES = (JobStatus.LEASED.value, JobStatus.RUNNING.value)


def release_expired_leases(session: Session, now: datetime | None = None) -> int:
    """Requeue jobs whose lease expired; a dead worker must not strand a document.

    RUNNING is swept as well as LEASED: only the worker holding the job ever moves it
    out of RUNNING, so a worker that dies mid-parse would otherwise strand the job (and
    its document) forever.
    """
    moment = now or _now()
    stale = session.scalars(select(Job).where(Job.status.in_(EXPIRABLE_JOB_STATUSES))).all()
    requeued = 0
    for job in stale:
        expires_at = _aware(job.lease_expires_at)
        if expires_at is not None and expires_at > moment:
            continue
        set_job_status(job, JobStatus.QUEUED)
        job.leased_by = None
        job.lease_expires_at = None
        job.available_at = moment
        document = session.get(Document, job.document_id)
        if document is not None:
            # A RUNNING job left the document mid-pipeline; the retry restarts from
            # the queue, so the document has to follow it back.
            set_document_status(document, DocumentStatus.QUEUED_FOR_PARSE)
        requeued += 1
    if requeued:
        session.flush()
    return requeued


def _runnable_job_query(session: Session, moment: datetime) -> Select[tuple[Job]]:
    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.QUEUED.value,
            or_(Job.available_at.is_(None), Job.available_at <= moment),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .limit(1)
    )
    if session.get_bind().dialect.name == "sqlite":
        # SQLite has neither row locks nor SKIP LOCKED; the compare-and-swap below is
        # what actually makes the claim safe, so the plain SELECT is fine here.
        return stmt
    return stmt.with_for_update(skip_locked=True)


def _claim_job(
    session: Session,
    job: Job,
    worker_id: str,
    moment: datetime,
    settings: Settings,
) -> bool:
    """Compare-and-swap the lease onto a job; False means another worker won the race.

    The `status == QUEUED` predicate is the guard: without it a PK-only UPDATE would
    let two workers lease the same job and collide on `uq_parse_runs_version` later.
    """
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.LEASED.value,
                leased_by=worker_id,
                lease_expires_at=moment + timedelta(seconds=settings.job_lease_seconds),
                updated_at=_now(),
            )
        ),
    )
    session.refresh(job)
    return result.rowcount == 1


def lease_next_job(
    session: Session,
    worker_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> Job | None:
    """Lease the oldest runnable job for this worker, or return None."""
    moment = now or _now()
    release_expired_leases(session, moment)

    while True:
        job = session.scalar(_runnable_job_query(session, moment))
        if job is None:
            return None
        if _claim_job(session, job, worker_id, moment, settings):
            return job


# ---------------------------------------------------------------------- execution


def _field_value(canonical: CanonicalDocument, name: str) -> str | None:
    for field in canonical.extracted_fields:
        if field.name == name:
            return field.normalized_value
    return None


def _as_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_extracted_fields(document: Document, canonical: CanonicalDocument) -> None:
    document.document_type = _field_value(canonical, "document_type")
    document.document_number = _field_value(canonical, "document_number")
    document.title = _field_value(canonical, "title")
    document.issuer = _field_value(canonical, "issuer")
    document.signer = _field_value(canonical, "signer")

    issued = _as_date(_field_value(canonical, "issue_date"))
    document.issued_date = issued.date() if issued is not None else None
    deadline = _as_date(_field_value(canonical, "deadline"))
    document.deadline = deadline.date() if deadline is not None else None

    document.requires_user_review = canonical.quality_report.requires_user_review


def _record_parse_run(
    session: Session,
    document: Document,
    job: Job,
    result_canonical: CanonicalDocument,
    route: str,
    strategy_decided: bool,
    degraded: bool,
    inspection: dict[str, object],
) -> ParseRun:
    version = next_parse_run_version(session, document.id)

    # Exactly one current version. Superseded runs are kept, never overwritten.
    for previous in session.scalars(
        select(ParseRun).where(ParseRun.document_id == document.id, ParseRun.is_current.is_(True))
    ).all():
        previous.is_current = False

    parser_run = result_canonical.parser_run
    run = ParseRun(
        id=new_id("prun"),
        document_id=document.id,
        job_id=job.id,
        version=version,
        is_current=True,
        parser_name=parser_run.parser_name,
        parser_version=parser_run.parser_version,
        configuration_hash=parser_run.configuration_hash,
        strategy_decided=strategy_decided,
        degraded=degraded,
        route=route,
        schema_version=result_canonical.schema_version,
        canonical=result_canonical.model_dump(mode="json"),
        inspection=inspection,
        quality_report=result_canonical.quality_report.model_dump(mode="json"),
        started_at=datetime.fromisoformat(parser_run.started_at),
        finished_at=datetime.fromisoformat(parser_run.finished_at),
        created_at=_now(),
    )
    session.add(run)
    session.flush()

    document.current_parse_run_id = run.id
    return run


def _fail_job(
    session: Session,
    job: Job,
    document: Document,
    error: ParserError,
    settings: Settings,
) -> None:
    payload = error.to_dict()
    retryable = error.retryable and error.code not in TERMINAL_PARSER_CODES
    job.attempt += 1
    job.leased_by = None
    job.lease_expires_at = None
    job.error = payload

    if retryable and job.attempt < job.max_attempts:
        set_job_status(job, JobStatus.FAILED_RETRYABLE)
        set_job_status(job, JobStatus.QUEUED)
        job.available_at = _now() + timedelta(seconds=settings.job_retry_backoff_seconds)
        set_document_status(document, DocumentStatus.QUEUED_FOR_PARSE)
    else:
        set_job_status(job, JobStatus.FAILED_TERMINAL)
        if error.code in UNSUPPORTED_PARSER_CODES:
            set_document_status(document, DocumentStatus.UNSUPPORTED)
        else:
            set_document_status(document, DocumentStatus.PARSE_FAILED)

    document.error_code = payload["code"]
    document.error_message = payload["message"]
    session.commit()


def _load_strategy(path: str | None) -> ParserStrategy:
    """Load the strategy, mapping malformed configuration onto a structured error.

    A broken file must fail the one job, not raise out of the worker loop and
    crash-loop the process.
    """
    try:
        return load_strategy(path)
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError(
            ParserErrorCode.PARSER_STRATEGY_UNDECIDED,
            f"parser strategy configuration is unusable: {exc}",
            parser_name="strategy",
        ) from exc


def run_job(
    session: Session,
    job: Job,
    storage: ObjectStorage,
    settings: Settings,
) -> ParseRun | None:
    """Execute one leased parse job. Returns the new parse run, or None on failure."""
    document = session.get(Document, job.document_id)
    if document is None:  # pragma: no cover - foreign key makes this unreachable
        raise errors.ApiError(errors.NOT_FOUND, "document not found", status_code=404)

    set_job_status(job, JobStatus.RUNNING)
    set_document_status(document, DocumentStatus.INSPECTING)
    document.error_code = None
    document.error_message = None
    session.commit()

    try:
        strategy = _load_strategy(settings.parser_strategy_path)
        pdf_path = storage.local_path(document.storage_uri)
        set_document_status(document, DocumentStatus.PARSING)
        session.commit()

        result = run_ingestion(
            pdf_path,
            document_id=document.id,
            strategy=strategy,
            environment=settings.app_env,
        )
    except ParserError as exc:
        _fail_job(session, job, document, exc, settings)
        return None
    except StorageError as exc:
        _fail_job(
            session,
            job,
            document,
            ParserError(
                ParserErrorCode.UNSUPPORTED_INPUT,
                f"stored original could not be read: {exc}",
                parser_name="storage",
            ),
            settings,
        )
        return None

    set_document_status(document, DocumentStatus.NORMALIZING)
    set_document_status(document, DocumentStatus.STRUCTURING)

    run = _record_parse_run(
        session,
        document,
        job,
        result.canonical,
        route=result.inspection.route.value,
        strategy_decided=result.selection.strategy_decided,
        degraded=result.selection.degraded,
        inspection=result.inspection.model_dump(mode="json"),
    )
    _apply_extracted_fields(document, result.canonical)

    job.attempt += 1
    job.leased_by = None
    job.lease_expires_at = None
    job.error = None
    set_job_status(job, JobStatus.SUCCEEDED)
    set_document_status(document, DocumentStatus.READY_FOR_REVIEW)
    session.commit()
    return run


def reprocess_document(
    session: Session,
    document: Document,
    settings: Settings,
    reason: str = "reprocess",
) -> Job:
    """Queue a new parse run for a document without touching earlier runs."""
    status = DocumentStatus(document.status)
    if status in (
        DocumentStatus.QUEUED_FOR_PARSE,
        DocumentStatus.INSPECTING,
        DocumentStatus.PARSING,
        DocumentStatus.NORMALIZING,
        DocumentStatus.STRUCTURING,
    ):
        raise errors.ApiError(
            errors.CONFLICT,
            "the document is already being processed",
            status_code=409,
            details={"status": document.status},
        )
    if status == DocumentStatus.UNSUPPORTED:
        raise errors.ApiError(
            errors.CONFLICT,
            "the document is unsupported and cannot be reprocessed",
            status_code=409,
            details={"status": document.status},
        )

    job = enqueue_parse_job(
        session, document, reason=reason, max_attempts=settings.job_max_attempts
    )
    session.commit()
    return job
