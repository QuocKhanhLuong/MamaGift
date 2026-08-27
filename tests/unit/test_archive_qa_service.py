"""Unit tests for ArchiveQaService — grounded cross-document answering."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document, DocumentChunk, ParseRun
from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_rag.archive_service import (
    ArchiveQaAnswer,
    ArchiveQaService,
    ArchiveRelationRef,
)
from mamagift_rag.schema import Citation, ModelRef, QaAnswer, RetrievalRef
from mamagift_rag.service import QaService
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.index import SqlDocumentIndex
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.scope import EvidenceScope

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
EMBEDDING_VERSION = "bge-m3-v1"
DIM = 8


def _vec(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIM - 1)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _seed(
    session_factory: sessionmaker[Session],
    doc_id: str,
    *,
    number: str,
    text: str,
    issued: date,
    chunk_id: str,
    embedding: list[float] | None = None,
) -> None:
    run_id = f"prun_{doc_id}"
    with session_factory() as session, session.begin():
        session.add(
            Document(
                id=doc_id,
                filename=f"{doc_id}.pdf",
                content_type="application/pdf",
                byte_size=2048,
                checksum_sha256=f"sha_{doc_id}",
                storage_uri=f"local://{doc_id}",
                document_type="Công văn",
                document_number=number,
                title=f"Tiêu đề {doc_id}",
                issuer="UBND Tỉnh",
                issued_date=issued,
                current_parse_run_id=run_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ParseRun(
                id=run_id,
                document_id=doc_id,
                version=1,
                is_current=True,
                parser_name="pymupdf",
                parser_version="1.0",
                configuration_hash="h",
                strategy_decided=True,
                degraded=False,
                route="born_digital",
                schema_version="1.0",
                canonical={},
                inspection={},
                quality_report={},
                started_at=NOW,
                finished_at=NOW,
                created_at=NOW,
            )
        )
        session.add(
            DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                parse_run_id=run_id,
                document_version=1,
                chunk_index=0,
                section_path=["Điều 1"],
                page_numbers=[1],
                source_block_ids=[f"blk_{chunk_id}"],
                text=text,
                token_count=len(text.split()),
                embedding=embedding or _vec(1.0),
                embedding_model="bge-m3",
                embedding_version=EMBEDDING_VERSION,
                created_at=NOW,
            )
        )


def _archive_scope() -> EvidenceScope:
    return EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)


def _service(
    session_factory: sessionmaker[Session],
    chat: FakeChatProvider,
) -> ArchiveQaService:
    return ArchiveQaService(
        chat_provider=chat,
        embedding_provider=FakeEmbeddingProvider(
            model_id="bge-m3", embedding_version=EMBEDDING_VERSION, dimension=DIM
        ),
        archive_index=SqlArchiveIndex(session_factory, default_embedding_version=EMBEDDING_VERSION),
        reranker=FakeReranker(cross_document=True),
    )


def _answer_json(citations: list[dict[str, object]], *, status: str = "answered") -> str:
    return json.dumps(
        {"answer": "Câu trả lời có căn cứ.", "status": status, "citations": citations}
    )


def _two_documents(session_factory: sessionmaker[Session]) -> None:
    _seed(
        session_factory,
        "doc_a",
        number="19/2026/TT-BGDĐT",
        text="Thông tư quy định về tuyển sinh đầu cấp năm 2026.",
        issued=date(2026, 3, 31),
        chunk_id="doc_a:c1",
        embedding=_vec(1.0),
    )
    _seed(
        session_factory,
        "doc_b",
        number="57/QĐ-UBND",
        text="Quyết định về tuyển sinh và kế hoạch triển khai.",
        issued=date(2026, 1, 15),
        chunk_id="doc_b:c1",
        embedding=_vec(0.9),
    )


def test_answers_across_multiple_documents_and_partitions_citations(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    chat = FakeChatProvider(
        responses=[_answer_json([{"citation_id": "c1"}, {"citation_id": "c2"}])]
    )
    result = asyncio.run(
        _service(session_factory, chat).answer("tuyển sinh", scope=_archive_scope())
    )

    assert result.status == "answered"
    assert len(result.document_groups) >= 2

    grouped = [cid for group in result.document_groups for cid in group.citation_ids]
    assert sorted(grouped) == sorted(c.citation_id for c in result.citations)
    # Every citation lands in exactly one group.
    assert len(grouped) == len(set(grouped))
    for group in result.document_groups:
        for citation_id in group.citation_ids:
            citation = next(c for c in result.citations if c.citation_id == citation_id)
            assert citation.document_id == group.document_id


def test_scope_guards_are_exact_mirrors(session_factory: sessionmaker[Session]) -> None:
    """ArchiveQaService refuses a pinned document; QaService refuses an archive wildcard.

    Asserting both here makes the separation visible in one place: neither service can be
    used to do the other's job, so selected-document QA stays incapable of cross-document
    retrieval and archive QA cannot collapse into a single global document index.
    """
    _two_documents(session_factory)
    chat = FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])])
    archive_service = _service(session_factory, chat)

    document_scope = EvidenceScope(
        family_id=AUTHORITATIVE_FAMILY_ID,
        document_id="doc_a",
        document_version=1,
        parse_run_id="prun_doc_a",
    )
    archive_result = asyncio.run(archive_service.answer("tuyển sinh", scope=document_scope))
    assert archive_result.status == "failed"
    assert archive_result.citations == []

    document_service = QaService(
        chat_provider=FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])]),
        embedding_provider=FakeEmbeddingProvider(
            model_id="bge-m3", embedding_version=EMBEDDING_VERSION, dimension=DIM
        ),
        document_index=SqlDocumentIndex(
            session_factory, default_embedding_version=EMBEDDING_VERSION
        ),
        reranker=FakeReranker(cross_document=True),
    )
    document_result = asyncio.run(document_service.answer("tuyển sinh", scope=_archive_scope()))
    assert document_result.status == "failed"
    assert document_result.citations == []


def test_citation_outside_the_allow_list_yields_failed(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    forged = _answer_json(
        [{"citation_id": "c1", "document_id": "doc_not_in_archive", "page_number": 1}]
    )
    result = asyncio.run(
        _service(session_factory, FakeChatProvider(responses=[forged])).answer(
            "tuyển sinh", scope=_archive_scope()
        )
    )
    assert result.status == "failed"
    assert result.citations == []
    assert result.document_groups == []


def test_unknown_citation_id_yields_failed(session_factory: sessionmaker[Session]) -> None:
    _two_documents(session_factory)
    result = asyncio.run(
        _service(
            session_factory, FakeChatProvider(responses=[_answer_json([{"citation_id": "c99"}])])
        ).answer("tuyển sinh", scope=_archive_scope())
    )
    assert result.status == "failed"


def test_answered_with_no_citations_is_downgraded_to_abstention(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    result = asyncio.run(
        _service(session_factory, FakeChatProvider(responses=[_answer_json([])])).answer(
            "tuyển sinh", scope=_archive_scope()
        )
    )
    assert result.status == "insufficient_evidence"
    assert result.citations == []


def test_empty_archive_abstains_with_the_fixed_message(
    session_factory: sessionmaker[Session],
) -> None:
    chat = FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])])
    result = asyncio.run(_service(session_factory, chat).answer("gì đó", scope=_archive_scope()))
    assert result.status == "insufficient_evidence"
    assert result.answer == "Không tìm thấy văn bản nào phù hợp trong kho tài liệu."
    assert result.document_groups == []
    assert chat.calls == []


def test_worker_unavailable_and_generic_worker_error(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    unavailable = asyncio.run(
        _service(
            session_factory,
            FakeChatProvider(
                responses=[WorkerError(code=WorkerErrorCode.UNAVAILABLE, message="down")]
            ),
        ).answer("tuyển sinh", scope=_archive_scope())
    )
    assert unavailable.status == "ai_worker_unavailable"

    generic = asyncio.run(
        _service(
            session_factory,
            FakeChatProvider(
                responses=[WorkerError(code=WorkerErrorCode.BAD_REQUEST, message="bad")]
            ),
        ).answer("tuyển sinh", scope=_archive_scope())
    )
    assert generic.status == "failed"


def test_relations_are_never_synthesised_and_unsupported_ones_are_dropped(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    chat = FakeChatProvider(
        responses=[_answer_json([{"citation_id": "c1"}, {"citation_id": "c2"}])]
    )
    service = _service(session_factory, chat)

    without = asyncio.run(service.answer("tuyển sinh", scope=_archive_scope()))
    assert without.relations == []

    chat.add_response(_answer_json([{"citation_id": "c1"}, {"citation_id": "c2"}]))
    supported = ArchiveRelationRef(
        relation_type="replaces",
        review_state="unverified",
        confidence=0.9,
        source_document_id="doc_a",
        target_document_id="doc_b",
        target_document_number="57/QĐ-UBND",
        citation_ids=["c1"],
    )
    uncited = supported.model_copy(
        update={"source_document_id": "doc_x", "target_document_id": None, "citation_ids": ["c1"]}
    )
    unsupported_citation = supported.model_copy(update={"citation_ids": ["c404"]})

    with_relations = asyncio.run(
        service.answer(
            "tuyển sinh",
            scope=_archive_scope(),
            relations=[supported, uncited, unsupported_citation],
        )
    )
    assert [r.relation_type for r in with_relations.relations] == ["replaces"]
    assert with_relations.relations[0].review_state == "unverified"


def test_freshness_caveat_is_present_only_for_a_freshness_question(
    session_factory: sessionmaker[Session],
) -> None:
    _two_documents(session_factory)
    chat = FakeChatProvider(
        responses=[
            _answer_json([{"citation_id": "c1"}]),
            _answer_json([{"citation_id": "c1"}]),
        ]
    )
    service = _service(session_factory, chat)

    fresh = asyncio.run(
        service.answer("Văn bản mới nhất về tuyển sinh là gì?", scope=_archive_scope())
    )
    assert fresh.freshness_caveat is not None
    assert "thay thế" in fresh.freshness_caveat

    plain = asyncio.run(service.answer("tuyển sinh gồm những gì?", scope=_archive_scope()))
    assert plain.freshness_caveat is None


def test_budget_is_spent_from_the_archive_category(
    session_factory: sessionmaker[Session],
) -> None:
    """The archive path must not spend the selected-document budget.

    If it did, the breakdown would misreport where an archive answer's context came from.
    """
    _two_documents(session_factory)
    service = _service(
        session_factory, FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])])
    )
    captured: dict[str, object] = {}
    original = service._retriever.retrieve

    async def _spy(*args: object, **kwargs: object) -> object:
        result = await original(*args, **kwargs)  # type: ignore[arg-type]
        captured["result"] = result
        return result

    service._retriever.retrieve = _spy  # type: ignore[assignment,method-assign]
    answer = asyncio.run(service.answer("tuyển sinh", scope=_archive_scope()))
    assert isinstance(answer, ArchiveQaAnswer)

    from mamagift_retrieval.evidence.archive_assembler import assemble_archive_evidence

    retrieved = captured["result"]
    evidence = assemble_archive_evidence(
        retrieved.candidates,  # type: ignore[attr-defined]
        scope=_archive_scope(),
        budget=service._budget,
        query_id="q",
        allowed_documents=set(retrieved.allowed_document_ids),  # type: ignore[attr-defined]
    )
    usage = {c.category: c for c in evidence.budget.categories}
    assert usage["archive_semantic"].used_chars > 0
    assert usage["selected_document"].used_chars == 0


def test_post_validation_allow_list_catches_a_citation_validation_escape(
    session_factory: sessionmaker[Session],
) -> None:
    """A citation for a document that was never retrieved can never reach the client.

    Validation is stubbed to wave one through, simulating a bug in citation validation. The
    answer must come back 'failed' with nothing cited, because a citation whose document was
    not retrieved has no group to belong to and would be unopenable in the UI.
    """
    _two_documents(session_factory)
    service = _service(
        session_factory,
        FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])]),
    )

    escaped = QaAnswer(
        answer="Câu trả lời vượt rào.",
        status="answered",
        citations=[
            Citation(
                citation_id="c1",
                document_id="doc_never_retrieved",
                page_number=1,
                block_ids=["blk"],
                quote=None,
            )
        ],
        retrieval=RetrievalRef(query_id="q"),
        model=ModelRef(provider="p", model="m", version="v"),
    )

    with mock.patch("mamagift_rag.archive_service.parse_and_validate_answer", return_value=escaped):
        result = asyncio.run(service.answer("tuyển sinh", scope=_archive_scope()))

    assert result.status == "failed"
    assert result.citations == []
    assert result.document_groups == []


def test_grouping_failure_is_reported_as_failed_not_as_a_partial_answer(
    session_factory: sessionmaker[Session],
) -> None:
    """A citation that lands in no document group would be unreachable in the UI.

    The service must refuse the whole answer rather than return citations the reader cannot
    open. Validation is stubbed to return a citation whose id is not in the evidence set.
    """
    _two_documents(session_factory)
    service = _service(
        session_factory,
        FakeChatProvider(responses=[_answer_json([{"citation_id": "c1"}])]),
    )

    ungroupable = QaAnswer(
        answer="Câu trả lời không nhóm được.",
        status="answered",
        citations=[
            Citation(
                citation_id="c_not_in_evidence",
                document_id="doc_a",
                page_number=1,
                block_ids=["blk"],
                quote=None,
            )
        ],
        retrieval=RetrievalRef(query_id="q"),
        model=ModelRef(provider="p", model="m", version="v"),
    )

    with mock.patch(
        "mamagift_rag.archive_service.parse_and_validate_answer", return_value=ungroupable
    ):
        result = asyncio.run(service.answer("tuyển sinh", scope=_archive_scope()))

    assert result.status == "failed"
    assert result.citations == []
