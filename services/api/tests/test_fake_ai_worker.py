import asyncio

from app.fake_ai_worker import FakeAIWorker
from mamagift_contracts import ParseJobInput, ParseJobRequest, ParserSpec


def make_request() -> ParseJobRequest:
    return ParseJobRequest(
        job_id="job_phase0",
        idempotency_key="idem_phase0",
        document_id="doc_phase0",
        input=ParseJobInput(
            object_uri="local://phase0/synthetic.pdf",
            checksum_sha256="0" * 64,
        ),
        parser=ParserSpec(name="fake-contract-only"),
    )


def test_fake_worker_preserves_typed_job_identity_without_intelligence() -> None:
    worker = FakeAIWorker()
    health = asyncio.run(worker.health())
    accepted = asyncio.run(worker.submit_parse_job(make_request()))

    assert health.worker_version == "fake-contract-only-0.1.0"
    assert health.status == "degraded"
    assert health.capabilities.model_dump() == {
        "parse": False,
        "embed": False,
        "rerank": False,
        "llm": False,
    }
    assert health.models == {}
    assert accepted.status == "accepted"
    assert accepted.implementation == "fake-contract-only"
    assert accepted.job_id == "job_phase0"
    assert accepted.document_id == "doc_phase0"
