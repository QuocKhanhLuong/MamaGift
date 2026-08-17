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

from . import ingestion
from .db import get_session_factory
from .dependencies import get_storage
from .models import ParseRun
from .settings import Settings, get_settings
from .storage import ObjectStorage


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{ingestion.new_id('w')}"


def process_next_job(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    worker_id: str,
) -> ParseRun | None:
    """Lease and run at most one job. Returns None when there is nothing to do."""
    job = ingestion.lease_next_job(session, worker_id, settings)
    if job is None:
        return None
    return ingestion.run_job(session, job, storage, settings)


def drain(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    worker_id: str,
    max_jobs: int = 100,
) -> int:
    """Run queued jobs until the queue is empty or `max_jobs` is reached."""
    processed = 0
    while processed < max_jobs:
        job = ingestion.lease_next_job(session, worker_id, settings)
        if job is None:
            break
        ingestion.run_job(session, job, storage, settings)
        processed += 1
    return processed


def main() -> int:  # pragma: no cover - process entry point
    parser = argparse.ArgumentParser(description="MamaGift parse worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")
    args = parser.parse_args()

    settings = get_settings()
    storage = get_storage()
    worker_id = default_worker_id()
    session_factory = get_session_factory()

    while True:
        with session_factory() as session:
            processed = drain(session, storage, settings, worker_id)
        if args.once:
            print(f"processed {processed} job(s)")
            return 0
        if processed == 0:
            time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
