"""State machine tests: every legal transition, and rejection of illegal ones."""

from __future__ import annotations

import itertools

import pytest

from app.state_machine import (
    DOCUMENT_TRANSITIONS,
    JOB_TRANSITIONS,
    DocumentStatus,
    IllegalTransitionError,
    JobStatus,
    assert_document_transition,
    assert_job_transition,
    can_transition_document,
    can_transition_job,
)

LEGAL_DOCUMENT_TRANSITIONS = [
    (current, target)
    for current, targets in DOCUMENT_TRANSITIONS.items()
    for target in sorted(targets)
]
ILLEGAL_DOCUMENT_TRANSITIONS = [
    (current, target)
    for current, target in itertools.product(DocumentStatus, DocumentStatus)
    if target not in DOCUMENT_TRANSITIONS[current]
]
LEGAL_JOB_TRANSITIONS = [
    (current, target) for current, targets in JOB_TRANSITIONS.items() for target in sorted(targets)
]
ILLEGAL_JOB_TRANSITIONS = [
    (current, target)
    for current, target in itertools.product(JobStatus, JobStatus)
    if target not in JOB_TRANSITIONS[current]
]


def test_every_status_is_declared_in_the_machine() -> None:
    assert set(DOCUMENT_TRANSITIONS) == set(DocumentStatus)
    assert set(JOB_TRANSITIONS) == set(JobStatus)


@pytest.mark.parametrize(("current", "target"), LEGAL_DOCUMENT_TRANSITIONS)
def test_legal_document_transitions_are_allowed(
    current: DocumentStatus, target: DocumentStatus
) -> None:
    assert can_transition_document(current, target)
    assert_document_transition(current, target)


@pytest.mark.parametrize(("current", "target"), ILLEGAL_DOCUMENT_TRANSITIONS)
def test_illegal_document_transitions_are_rejected(
    current: DocumentStatus, target: DocumentStatus
) -> None:
    assert not can_transition_document(current, target)
    with pytest.raises(IllegalTransitionError):
        assert_document_transition(current, target)


@pytest.mark.parametrize(("current", "target"), LEGAL_JOB_TRANSITIONS)
def test_legal_job_transitions_are_allowed(current: JobStatus, target: JobStatus) -> None:
    assert can_transition_job(current, target)
    assert_job_transition(current, target)


@pytest.mark.parametrize(("current", "target"), ILLEGAL_JOB_TRANSITIONS)
def test_illegal_job_transitions_are_rejected(current: JobStatus, target: JobStatus) -> None:
    assert not can_transition_job(current, target)
    with pytest.raises(IllegalTransitionError):
        assert_job_transition(current, target)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert DOCUMENT_TRANSITIONS[DocumentStatus.UNSUPPORTED] == frozenset()
    assert JOB_TRANSITIONS[JobStatus.SUCCEEDED] == frozenset()
    assert JOB_TRANSITIONS[JobStatus.FAILED_TERMINAL] == frozenset()


def test_a_failed_document_can_only_move_back_through_the_queue() -> None:
    assert DOCUMENT_TRANSITIONS[DocumentStatus.PARSE_FAILED] == frozenset(
        {DocumentStatus.QUEUED_FOR_PARSE}
    )


def test_worker_availability_is_not_a_document_state() -> None:
    """Worker health must never be encoded by corrupting document status."""
    assert not any("WORKER" in status.value for status in DocumentStatus)
