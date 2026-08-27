"""The Kế hoạch hard gate: task, owner and deadline must never cross documents.

This is the correctness test Phase 5 exists to protect. Three Kế hoạch documents each carry
several tasks with distinct owners and deadlines. The test drives the FULL pipeline --
canonical fixture, `build_chunks`, persisted `document_chunks`, archive lexical + dense
retrieval, RRF, reranking, multi-document evidence assembly, grounded QA and citation
validation -- and asserts BOTH directions for every pair: a task must resolve to its own
owner and deadline, and must NOT resolve to another task's.

Both directions matter. Asserting only "Task A has Owner A" passes trivially against an
implementation that attaches every owner to every task.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Document, DocumentChunk, ParseRun
from mamagift_docpipe import (
    BlockProvenance,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalPage,
    ExtractedField,
    Extractor,
    ParserRun,
    QualityReport,
)
from mamagift_rag.archive_service import ArchiveQaService
from mamagift_retrieval.archive.protocol import AUTHORITATIVE_FAMILY_ID
from mamagift_retrieval.archive.sql_archive_index import SqlArchiveIndex
from mamagift_retrieval.chunk import ChunkType
from mamagift_retrieval.chunking import build_chunks
from mamagift_retrieval.evidence.archive_assembler import (
    assemble_archive_evidence,
    render_evidence_text,
)
from mamagift_retrieval.providers import FakeChatProvider, FakeEmbeddingProvider
from mamagift_retrieval.rerank import FakeReranker
from mamagift_retrieval.scope import EvidenceScope

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
DIM = 1024
EMBEDDING_VERSION = "fake-bge-m3-v1"


@dataclass(frozen=True)
class Task:
    ordinal: str
    title: str
    owner: str
    deadline: str


@dataclass(frozen=True)
class PlanFixture:
    document_id: str
    number: str
    issued: date
    tasks: tuple[Task, ...]


PLANS: tuple[PlanFixture, ...] = (
    PlanFixture(
        document_id="doc_kh_1",
        number="12/KH-UBND",
        issued=date(2026, 6, 1),
        tasks=(
            Task(
                "1",
                "Rà soát danh sách học sinh trong độ tuổi tuyển sinh",
                "Phòng Giáo dục và Đào tạo",
                "trước ngày 15 tháng 08 năm 2026",
            ),
            Task(
                "2",
                "Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến",
                "Trường Tiểu học Mai Giang",
                "trước ngày 30 tháng 08 năm 2026",
            ),
        ),
    ),
    PlanFixture(
        document_id="doc_kh_2",
        number="27/KH-UBND",
        issued=date(2026, 6, 15),
        tasks=(
            Task(
                "1",
                "Kiểm tra cơ sở vật chất phòng học",
                "Ban Quản lý dự án huyện",
                "trước ngày 10 tháng 07 năm 2026",
            ),
            Task(
                "2",
                "Bồi dưỡng nghiệp vụ cho giáo viên chủ nhiệm",
                "Trung tâm Bồi dưỡng Chính trị",
                "trước ngày 20 tháng 07 năm 2026",
            ),
        ),
    ),
    PlanFixture(
        document_id="doc_kh_3",
        number="41/KH-UBND",
        issued=date(2026, 7, 1),
        tasks=(
            Task(
                "1",
                "Xây dựng phương án phân tuyến tuyển sinh",
                "Ủy ban nhân dân xã Mai Giang",
                "trước ngày 05 tháng 09 năm 2026",
            ),
            Task(
                "2",
                "Công bố kết quả tuyển sinh trên cổng thông tin",
                "Văn phòng Ủy ban nhân dân huyện",
                "trước ngày 25 tháng 09 năm 2026",
            ),
        ),
    ),
)

ALL_TASKS: tuple[tuple[PlanFixture, Task], ...] = tuple(
    (plan, task) for plan in PLANS for task in plan.tasks
)


def _canonical(plan: PlanFixture) -> CanonicalDocument:
    lines = ["I. MỤC ĐÍCH, YÊU CẦU", "Bảo đảm công tác tuyển sinh đúng quy định.", "II. NỘI DUNG"]
    for task in plan.tasks:
        lines.append(f"{task.ordinal}. {task.title}")
        lines.append(f"Đơn vị chủ trì: {task.owner}")
        lines.append(f"Thời hạn hoàn thành: {task.deadline}")

    blocks = [
        CanonicalBlock(
            id=f"b_1_{index:04d}",
            type=BlockType.PARAGRAPH,
            text=line,
            reading_order=index,
            provenance=BlockProvenance(page_number=1),
        )
        for index, line in enumerate(lines)
    ]
    return CanonicalDocument(
        document_id=plan.document_id,
        parser_run=ParserRun(
            id=f"run_{plan.document_id}",
            parser_name="pymupdf",
            parser_version="1.0",
            configuration_hash="0" * 16,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        ),
        pages=[CanonicalPage(page_number=1, width=595.0, height=842.0, blocks=blocks)],
        extracted_fields=[
            ExtractedField(
                id="field_document_type",
                name="document_type",
                raw_value="ke_hoach",
                normalized_value="ke_hoach",
                extractor=Extractor(name="test", version="1.0"),
            ),
            ExtractedField(
                id="field_document_number",
                name="document_number",
                raw_value=plan.number,
                normalized_value=plan.number,
                extractor=Extractor(name="test", version="1.0"),
            ),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def _seed_plans(engine: Engine) -> sessionmaker[Session]:
    """Persist every plan through the real chunker into real document_chunks rows."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    provider = FakeEmbeddingProvider(dimension=DIM, embedding_version=EMBEDDING_VERSION)

    for plan in PLANS:
        run_id = f"run_{plan.document_id}"
        canonical = _canonical(plan)
        chunks = build_chunks(canonical, document_version=1)
        assert any(chunk.chunk_type == ChunkType.PLAN_TASK for chunk in chunks)

        vectors = asyncio.run(provider.embed_documents([chunk.text for chunk in chunks])).vectors

        with factory() as session, session.begin():
            session.add(
                Document(
                    id=plan.document_id,
                    filename=f"{plan.document_id}.pdf",
                    content_type="application/pdf",
                    byte_size=2048,
                    checksum_sha256=f"{plan.document_id}".ljust(64, "0"),
                    storage_uri=f"local://{plan.document_id}",
                    status="READY",
                    document_type="ke_hoach",
                    document_number=plan.number,
                    title=f"Kế hoạch {plan.number}",
                    issuer="UBND huyện",
                    issued_date=plan.issued,
                    current_parse_run_id=run_id,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                ParseRun(
                    id=run_id,
                    document_id=plan.document_id,
                    version=1,
                    is_current=True,
                    parser_name="pymupdf",
                    parser_version="1.0",
                    configuration_hash="0" * 16,
                    strategy_decided=True,
                    degraded=False,
                    route="born_digital",
                    schema_version="1.0",
                    canonical=json.loads(canonical.model_dump_json()),
                    inspection={},
                    quality_report={},
                    started_at=NOW,
                    finished_at=NOW,
                    created_at=NOW,
                )
            )
            for index, chunk in enumerate(chunks):
                session.add(
                    DocumentChunk(
                        id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        parse_run_id=chunk.parse_run_id,
                        document_version=chunk.document_version,
                        chunk_index=index,
                        parent_chunk_id=chunk.parent_chunk_id,
                        section_path=list(chunk.section_path),
                        page_numbers=list(chunk.source_page_numbers),
                        source_block_ids=list(chunk.source_block_ids),
                        text=chunk.text,
                        token_count=len(chunk.text.split()),
                        chunk_metadata=dict(chunk.metadata),
                        embedding=vectors[index],
                        embedding_model=provider.model_id,
                        embedding_version=EMBEDDING_VERSION,
                        created_at=NOW,
                    )
                )
    return factory


@pytest.fixture
def sqlite_plans() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return _seed_plans(engine)


@pytest.fixture
def postgres_plans(migrated_pg: Engine) -> sessionmaker[Session]:
    return _seed_plans(migrated_pg)


def _scope() -> EvidenceScope:
    return EvidenceScope(family_id=AUTHORITATIVE_FAMILY_ID, archive_scope=True)


def _retrieved_text(factory: sessionmaker[Session], query: str) -> tuple[str, set[str]]:
    """Run the real archive pipeline and return the joined evidence text plus its documents."""
    provider = FakeEmbeddingProvider(dimension=DIM, embedding_version=EMBEDDING_VERSION)
    chat = FakeChatProvider(
        responses=[json.dumps({"answer": "", "status": "insufficient_evidence", "citations": []})]
    )
    with factory() as session:
        service = ArchiveQaService(
            chat_provider=chat,
            embedding_provider=provider,
            archive_index=SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION),
            reranker=FakeReranker(cross_document=True),
        )
        retrieved = asyncio.run(service._retriever.retrieve(query, scope=_scope()))

    joined = "\n".join(candidate.chunk.text for candidate in retrieved.candidates)
    documents = {candidate.chunk.document_id for candidate in retrieved.candidates}
    return joined, documents


def _task_chunk_text(factory: sessionmaker[Session], plan: PlanFixture, task: Task) -> str:
    """The retrieved chunk that actually carries this task, plus its bounded ancestors."""
    provider = FakeEmbeddingProvider(dimension=DIM, embedding_version=EMBEDDING_VERSION)
    with factory() as session:
        index = SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION)
        hits = index.search_lexical(_scope(), task.title, top_k=20)
    assert hits, f"task {task.ordinal} of {plan.number} was not retrievable at all"

    best = next(
        (
            hit
            for hit in hits
            if hit.chunk.document_id == plan.document_id and task.title in hit.chunk.text
        ),
        None,
    )
    assert best is not None, (
        f"no chunk from {plan.document_id} carries task {task.ordinal!r}; "
        f"top hits came from {[hit.chunk.document_id for hit in hits[:3]]}"
    )
    assert provider.dimension == DIM

    # The chunker binds owner and deadline to the task as metadata rather than leaving them
    # loose in text. Assert BOTH that the association survived the database round trip and
    # that it reaches the evidence text a model would actually see -- if either is missing,
    # a grounded answer would have to guess who owns the task.
    assert best.chunk.metadata.get("owner") == task.owner
    assert best.chunk.metadata.get("deadline_raw") == task.deadline
    return render_evidence_text(best.chunk)


@pytest.mark.parametrize(
    ("plan", "task"), ALL_TASKS, ids=[f"{p.number}-task{t.ordinal}" for p, t in ALL_TASKS]
)
def test_task_keeps_its_own_owner_and_deadline_and_no_others(
    sqlite_plans: sessionmaker[Session], plan: PlanFixture, task: Task
) -> None:
    """Both directions, for every task in every plan.

    The chunk carrying a task must contain that task's owner and deadline, and must contain
    NO other task's owner or deadline -- including tasks in the same document, which is the
    easier failure mode, and tasks in other documents, which is the Phase 5 one.
    """
    text = _task_chunk_text(sqlite_plans, plan, task)

    assert task.owner in text, f"task {task.ordinal} lost its own owner"
    assert task.deadline in text, f"task {task.ordinal} lost its own deadline"

    for other_plan, other_task in ALL_TASKS:
        if other_plan.document_id == plan.document_id and other_task.ordinal == task.ordinal:
            continue
        if other_task.owner != task.owner:
            assert other_task.owner not in text, (
                f"task {task.ordinal} of {plan.number} absorbed the owner of "
                f"task {other_task.ordinal} of {other_plan.number}"
            )
        if other_task.deadline != task.deadline:
            assert other_task.deadline not in text, (
                f"task {task.ordinal} of {plan.number} absorbed the deadline of "
                f"task {other_task.ordinal} of {other_plan.number}"
            )


def test_cross_document_plan_query_reaches_every_plan(
    sqlite_plans: sessionmaker[Session],
) -> None:
    """The archive really is cross-document: one question reaches all three plans."""
    _, documents = _retrieved_text(sqlite_plans, "Đơn vị chủ trì và thời hạn hoàn thành")
    assert documents == {plan.document_id for plan in PLANS}


def test_grounded_answer_cites_only_the_document_that_holds_the_task(
    sqlite_plans: sessionmaker[Session],
) -> None:
    """End of the pipeline: a citation for a task resolves to that task's own document.

    The fake model is pointed at the evidence item that genuinely carries the task, the way a
    correct model would cite it. What is under test is everything after that: allow-list
    validation, the document/page/block resolution, and the grouping.
    """
    plan, task = PLANS[1], PLANS[1].tasks[0]
    provider = FakeEmbeddingProvider(dimension=DIM, embedding_version=EMBEDDING_VERSION)

    with sqlite_plans() as session:
        index = SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION)
        probe = ArchiveQaService(
            chat_provider=FakeChatProvider(
                responses=[
                    json.dumps({"answer": "", "status": "insufficient_evidence", "citations": []})
                ]
            ),
            embedding_provider=provider,
            archive_index=index,
            reranker=FakeReranker(cross_document=True),
        )
        retrieved = asyncio.run(probe._retriever.retrieve(task.title, scope=_scope()))
        evidence = assemble_archive_evidence(
            retrieved.candidates,
            scope=_scope(),
            budget=probe._budget,
            query_id="probe",
            allowed_documents=set(retrieved.allowed_document_ids),
        )

    target = next(
        (
            item
            for item in evidence.evidence
            if item.document_id == plan.document_id and task.title in item.text
        ),
        None,
    )
    assert target is not None, (
        f"the evidence set contains no item carrying task {task.ordinal} of {plan.number}; "
        f"it holds {[(i.citation_id, i.document_id) for i in evidence.evidence]}"
    )
    # The owner and deadline reached the evidence the model sees, so a grounded answer does
    # not have to guess them.
    assert task.owner in target.text
    assert task.deadline in target.text

    with sqlite_plans() as session:
        service = ArchiveQaService(
            chat_provider=FakeChatProvider(
                responses=[
                    json.dumps(
                        {
                            "answer": f"{task.title} do {task.owner} chủ trì, {task.deadline}.",
                            "status": "answered",
                            "citations": [{"citation_id": target.citation_id}],
                        },
                        ensure_ascii=False,
                    )
                ]
            ),
            embedding_provider=FakeEmbeddingProvider(
                dimension=DIM, embedding_version=EMBEDDING_VERSION
            ),
            archive_index=SqlArchiveIndex(session, default_embedding_version=EMBEDDING_VERSION),
            reranker=FakeReranker(cross_document=True),
        )
        answer = asyncio.run(service.answer(task.title, scope=_scope()))

    assert answer.status == "answered"
    assert {citation.document_id for citation in answer.citations} == {plan.document_id}
    assert [group.document_id for group in answer.document_groups] == [plan.document_id]
    assert answer.document_groups[0].document_number == plan.number
    for citation in answer.citations:
        assert citation.page_number in {1}
        assert citation.block_ids


@pytest.mark.parametrize(
    ("plan", "task"), ALL_TASKS, ids=[f"{p.number}-task{t.ordinal}" for p, t in ALL_TASKS]
)
def test_task_owner_deadline_association_holds_on_postgresql(
    postgres_plans: sessionmaker[Session], plan: PlanFixture, task: Task
) -> None:
    """The same gate against a real PostgreSQL + pgvector database, not just SQLite."""
    text = _task_chunk_text(postgres_plans, plan, task)

    assert task.owner in text
    assert task.deadline in text
    for other_plan, other_task in ALL_TASKS:
        if other_plan.document_id == plan.document_id and other_task.ordinal == task.ordinal:
            continue
        if other_task.owner != task.owner:
            assert other_task.owner not in text
        if other_task.deadline != task.deadline:
            assert other_task.deadline not in text
