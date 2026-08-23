"""The parse worker loop.

The worker is a separate process boundary on purpose: the API only enqueues, so an
unavailable worker leaves jobs retryable instead of corrupting document state
(`docs/08_API_AND_DATA_CONTRACTS.md` section 3).

Run one drain pass with:

    uv run python -m app.worker --once
"""

from __future__ import annotations

import argparse
import socket
import time

from sqlalchemy.orm import Session

from mamagift_retrieval.index import DocumentIndex
from mamagift_retrieval.providers import EmbeddingProvider

from . import indexing, ingestion
from .db import get_session_factory
from .dependencies import get_storage
from .models import Document, Job, JobStatus, ParseRun
from .settings import Settings, get_settings
from .state_machine import DocumentStatus, can_transition_document
from .storage import ObjectStorage


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{ingestion.new_id('w')}"


def _handle_job_failure(session: Session, job: Job, exc: Exception) -> None:
    """Record per-document job failure safely using the state machine and commit."""
    session.rollback()
    failed_job = session.get(Job, job.id)
    if failed_job is not None:
        failed_job.attempt += 1
        failed_job.leased_by = None
        failed_job.lease_expires_at = None
        failed_job.error = {
            "code": getattr(exc, "code", "processing_failure"),
            "message": str(exc),
        }
        ingestion.set_job_status(failed_job, JobStatus.FAILED_TERMINAL)

    failed_doc = session.get(Document, job.document_id)
    if failed_doc is not None:
        failed_doc.error_code = getattr(exc, "code", "processing_failure")
        failed_doc.error_message = str(exc)
        curr = DocumentStatus(failed_doc.status)
        if curr not in (DocumentStatus.PARSE_FAILED, DocumentStatus.UNSUPPORTED):
            if can_transition_document(curr, DocumentStatus.PARSE_FAILED):
                ingestion.set_document_status(failed_doc, DocumentStatus.PARSE_FAILED)
            elif curr == DocumentStatus.READY_FOR_REVIEW:
                ingestion.set_document_status(failed_doc, DocumentStatus.INDEXING)
                ingestion.set_document_status(failed_doc, DocumentStatus.PARSE_FAILED)
            else:
                failed_doc.status = DocumentStatus.PARSE_FAILED.value
    session.commit()


def process_next_job(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    worker_id: str,
    *,
    auto_index: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
) -> ParseRun | None:
    """Lease and run at most one job. Returns None when there is nothing to do."""
    job = ingestion.lease_next_job(session, worker_id, settings)
    if job is None:
        return None
    try:
        run = ingestion.run_job(session, job, storage, settings)
    except Exception as exc:
        _handle_job_failure(session, job, exc)
        return None

    if run is not None and (auto_index or embedding_provider is not None):
        try:
            indexing.index_parse_run_sync(
                session,
                run,
                embedding_provider=embedding_provider,
                document_index=document_index,
                settings=settings,
            )
        except Exception:
            # Per-document indexing failure is already recorded by index_parse_run.
            return None
    return run


def drain(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    worker_id: str,
    max_jobs: int = 100,
    *,
    auto_index: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
    document_index: DocumentIndex | None = None,
) -> int:
    """Run queued jobs until the queue is empty or `max_jobs` is reached."""
    processed = 0
    while processed < max_jobs:
        job = ingestion.lease_next_job(session, worker_id, settings)
        if job is None:
            break
        try:
            run = ingestion.run_job(session, job, storage, settings)
            if run is not None and (auto_index or embedding_provider is not None):
                try:
                    indexing.index_parse_run_sync(
                        session,
                        run,
                        embedding_provider=embedding_provider,
                        document_index=document_index,
                        settings=settings,
                    )
                except Exception:
                    # Indexing failure is recorded on the document. Loop continues.
                    pass
        except Exception as exc:
            _handle_job_failure(session, job, exc)
        processed += 1
    return processed


def main() -> int:  # pragma: no cover - process entry point
    parser = argparse.ArgumentParser(description="MamaGift parse worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")
    parser.add_argument("--index", action="store_true", help="run indexing pipeline after parsing")
    args = parser.parse_args()

    settings = get_settings()
    storage = get_storage()
    worker_id = default_worker_id()
    session_factory = get_session_factory()

    while True:
        try:
            with session_factory() as session:
                processed = drain(
                    session,
                    storage,
                    settings,
                    worker_id,
                    auto_index=args.index,
                )
        except Exception:
            processed = 0
        if args.once:
            print(f"processed {processed} job(s)")
            return 0
        if processed == 0:
            time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
