"""Document and job state machines.

Both machines are declared as data and enforced in one place. Illegal transitions
raise instead of silently writing a state nobody expects
(`docs/08_API_AND_DATA_CONTRACTS.md` sections 3 and 4).

Worker availability is deliberately *not* a document state: a job that cannot run
stays retryable and the document keeps its own status.
"""

from __future__ import annotations

from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    INSPECTING = "INSPECTING"
    QUEUED_FOR_PARSE = "QUEUED_FOR_PARSE"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    STRUCTURING = "STRUCTURING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    INDEXING = "INDEXING"
    READY = "READY"
    PARSE_FAILED = "PARSE_FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


DOCUMENT_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset(
        {DocumentStatus.INSPECTING, DocumentStatus.QUEUED_FOR_PARSE, DocumentStatus.UNSUPPORTED}
    ),
    DocumentStatus.INSPECTING: frozenset(
        {
            DocumentStatus.QUEUED_FOR_PARSE,
            DocumentStatus.PARSING,
            DocumentStatus.UNSUPPORTED,
            DocumentStatus.PARSE_FAILED,
        }
    ),
    DocumentStatus.QUEUED_FOR_PARSE: frozenset(
        {DocumentStatus.INSPECTING, DocumentStatus.PARSING, DocumentStatus.PARSE_FAILED}
    ),
    DocumentStatus.PARSING: frozenset(
        {
            DocumentStatus.NORMALIZING,
            DocumentStatus.QUEUED_FOR_PARSE,
            DocumentStatus.PARSE_FAILED,
            DocumentStatus.UNSUPPORTED,
        }
    ),
    DocumentStatus.NORMALIZING: frozenset(
        {DocumentStatus.STRUCTURING, DocumentStatus.PARSE_FAILED}
    ),
    DocumentStatus.STRUCTURING: frozenset(
        {DocumentStatus.READY_FOR_REVIEW, DocumentStatus.PARSE_FAILED}
    ),
    # INDEXING and READY belong to later phases; the transitions are declared so the
    # machine stays complete, but Phase 2 never enters them.
    DocumentStatus.READY_FOR_REVIEW: frozenset(
        {DocumentStatus.QUEUED_FOR_PARSE, DocumentStatus.INDEXING, DocumentStatus.READY}
    ),
    DocumentStatus.INDEXING: frozenset({DocumentStatus.READY, DocumentStatus.PARSE_FAILED}),
    DocumentStatus.READY: frozenset({DocumentStatus.QUEUED_FOR_PARSE}),
    DocumentStatus.PARSE_FAILED: frozenset({DocumentStatus.QUEUED_FOR_PARSE}),
    DocumentStatus.UNSUPPORTED: frozenset(),
}

JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.LEASED}),
    JobStatus.LEASED: frozenset({JobStatus.RUNNING, JobStatus.QUEUED}),
    # QUEUED is reachable from RUNNING so an expired lease can requeue a job whose
    # worker died mid-parse; nothing else ever moves a RUNNING job.
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED_RETRYABLE,
            JobStatus.FAILED_TERMINAL,
            JobStatus.QUEUED,
        }
    ),
    JobStatus.FAILED_RETRYABLE: frozenset({JobStatus.QUEUED, JobStatus.FAILED_TERMINAL}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED_TERMINAL: frozenset(),
}

TERMINAL_DOCUMENT_STATUSES = frozenset({DocumentStatus.UNSUPPORTED})
TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED_TERMINAL})


class IllegalTransitionError(RuntimeError):
    """Raised when code attempts a transition the machine does not allow."""

    def __init__(self, machine: str, current: str, target: str) -> None:
        super().__init__(f"illegal {machine} transition {current} -> {target}")
        self.machine = machine
        self.current = current
        self.target = target


def can_transition_document(current: DocumentStatus, target: DocumentStatus) -> bool:
    return target in DOCUMENT_TRANSITIONS[current]


def can_transition_job(current: JobStatus, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS[current]


def assert_document_transition(current: DocumentStatus, target: DocumentStatus) -> None:
    if not can_transition_document(current, target):
        raise IllegalTransitionError("document", current.value, target.value)


def assert_job_transition(current: JobStatus, target: JobStatus) -> None:
    if not can_transition_job(current, target):
        raise IllegalTransitionError("job", current.value, target.value)
