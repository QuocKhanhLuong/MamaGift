"""Sanitized multi-document evaluation corpus and fixture seeder for Phase 5 archive retrieval."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

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
from mamagift_retrieval.chunking import build_chunks
from mamagift_retrieval.providers import FakeEmbeddingProvider

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


def _normalize_doc_type(doc_type: str) -> str:
    normalized = doc_type.strip().lower()
    mapping = {
        "công văn": "cong_van",
        "kế hoạch": "ke_hoach",
        "quyết định": "quyet_dinh",
        "thông tư": "thong_tu",
        "nghị định": "nghi_dinh",
    }
    return mapping.get(normalized, normalized)


@dataclass(frozen=True)
class ArchiveFixtureDocument:
    document_id: str
    document_type: str  # "Công văn" | "Kế hoạch" | "Quyết định" | "Thông tư" | "Nghị định"
    document_number: str
    title: str
    issuer: str
    issued_date: date
    body_lines: tuple[str, ...]
    is_current: bool = True
    version: int = 1


ARCHIVE_CORPUS: tuple[ArchiveFixtureDocument, ...] = (
    # 1. Công văn
    ArchiveFixtureDocument(
        document_id="doc_cv_1",
        document_type="Công văn",
        document_number="105/CV-SGDĐT",
        title="Công văn về việc hướng dẫn tổ chức bồi dưỡng chuyên môn hè 2026",
        issuer="Sở Giáo dục và Đào tạo tỉnh Nam Hà",
        issued_date=date(2026, 5, 20),
        body_lines=(
            "Kính gửi: Các phòng Giáo dục và Đào tạo huyện, thị xã, thành phố.",
            (
                "Sở Giáo dục và Đào tạo hướng dẫn triển khai kế hoạch bồi dưỡng thường xuyên "
                "chuyên môn hè năm 2026 cho cán bộ quản lý và giáo viên."
            ),
            (
                "Yêu cầu các đơn vị lập danh sách học viên và gửi về Sở trước ngày "
                "15 tháng 06 năm 2026."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 2. Kế hoạch 1 (>= 2 tasks, distinct owners, distinct deadlines)
    ArchiveFixtureDocument(
        document_id="doc_kh_1",
        document_type="Kế hoạch",
        document_number="12/KH-UBND",
        title="Kế hoạch tổ chức tuyển sinh đầu cấp năm học 2026-2027",
        issuer="Ủy ban nhân dân huyện Tân Trào",
        issued_date=date(2026, 6, 1),
        body_lines=(
            "I. MỤC ĐÍCH, YÊU CẦU",
            "Bảo đảm công tác tuyển sinh đầu cấp đúng quy chế và công bằng.",
            "II. NỘI DUNG VÀ PHÂN CÔNG THỰC HIỆN",
            "1. Rà soát danh sách học sinh trong độ tuổi tuyển sinh",
            "Đơn vị chủ trì: Phòng Giáo dục và Đào tạo huyện",
            "Thời hạn hoàn thành: trước ngày 15 tháng 08 năm 2026",
            "2. Tổ chức tiếp nhận hồ sơ tuyển sinh trực tuyến",
            "Đơn vị chủ trì: Trường Tiểu học Mai Giang",
            "Thời hạn hoàn thành: trước ngày 30 tháng 08 năm 2026",
        ),
        is_current=True,
        version=1,
    ),
    # 3. Kế hoạch 2 (>= 2 tasks, distinct owners, distinct deadlines)
    ArchiveFixtureDocument(
        document_id="doc_kh_2",
        document_type="Kế hoạch",
        document_number="27/KH-UBND",
        title="Kế hoạch chuẩn bị cơ sở vật chất năm học mới 2026-2027",
        issuer="Ủy ban nhân dân huyện Tân Trào",
        issued_date=date(2026, 6, 15),
        body_lines=(
            "I. MỤC ĐÍCH, YÊU CẦU",
            "Nâng cao chất lượng cơ sở vật chất và đào tạo đội ngũ giáo viên.",
            "II. NỘI DUNG VÀ PHÂN CÔNG THỰC HIỆN",
            "1. Kiểm tra cơ sở vật chất phòng học và mua sắm thiết bị",
            "Đơn vị chủ trì: Ban Quản lý dự án huyện",
            "Thời hạn hoàn thành: trước ngày 10 tháng 07 năm 2026",
            "2. Bồi dưỡng nghiệp vụ cho giáo viên chủ nhiệm",
            "Đơn vị chủ trì: Trung tâm Bồi dưỡng Chính trị",
            "Thời hạn hoàn thành: trước ngày 20 tháng 07 năm 2026",
        ),
        is_current=True,
        version=1,
    ),
    # 4. Kế hoạch 3 (>= 2 tasks, distinct owners, distinct deadlines)
    ArchiveFixtureDocument(
        document_id="doc_kh_3",
        document_type="Kế hoạch",
        document_number="41/KH-UBND",
        title="Kế hoạch phân luồng học sinh sau tốt nghiệp trung học cơ sở",
        issuer="Ủy ban nhân dân huyện Tân Trào",
        issued_date=date(2026, 7, 1),
        body_lines=(
            "I. MỤC ĐÍCH, YÊU CẦU",
            "Đẩy mạnh công tác hướng nghiệp và phân luồng học sinh sau THCS.",
            "II. NỘI DUNG VÀ PHÂN CÔNG THỰC HIỆN",
            "1. Xây dựng phương án phân tuyến tuyển sinh và định hướng nghề",
            "Đơn vị chủ trì: Ủy ban nhân dân xã Mai Giang",
            "Thời hạn hoàn thành: trước ngày 05 tháng 09 năm 2026",
            "2. Công bố kết quả tuyển sinh và phân luồng trên cổng thông tin",
            "Đơn vị chủ trì: Văn phòng Ủy ban nhân dân huyện",
            "Thời hạn hoàn thành: trước ngày 25 tháng 09 năm 2026",
        ),
        is_current=True,
        version=1,
    ),
    # 5. Quyết định
    ArchiveFixtureDocument(
        document_id="doc_qd_1",
        document_type="Quyết định",
        document_number="57/QĐ-UBND",
        title="Quyết định ban hành Quy chế khen thưởng học sinh giỏi và giáo viên tiêu biểu",
        issuer="Ủy ban nhân dân tỉnh Nam Hà",
        issued_date=date(2025, 11, 10),
        body_lines=(
            "QUYẾT ĐỊNH:",
            (
                "Điều 1. Ban hành kèm theo Quyết định này Quy chế xét tặng danh hiệu "
                "khen thưởng học sinh giỏi các cấp."
            ),
            (
                "Điều 2. Chánh Văn phòng UBND tỉnh, Giám đốc Sở GDĐT và Chủ tịch UBND các huyện "
                "chịu trách nhiệm thi hành."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 6. Thông tư with distinctive number 19/2026/TT-BGDĐT
    ArchiveFixtureDocument(
        document_id="doc_tt_1",
        document_type="Thông tư",
        document_number="19/2026/TT-BGDĐT",
        title=(
            "Thông tư ban hành Quy chế tuyển sinh trình độ đại học và cao đẳng "
            "ngành Giáo dục Mầm non"
        ),
        issuer="Bộ Giáo dục và Đào tạo",
        issued_date=date(2026, 3, 31),
        body_lines=(
            "Điều 1. Phạm vi điều chỉnh và đối tượng áp dụng",
            (
                "Thông tư này quy định về tuyển sinh đại học chính quy và cao đẳng "
                "ngành Giáo dục Mầm non."
            ),
            "Điều 2. Nguyên tắc xét tuyển",
            (
                "Việc tuyển sinh phải bảo đảm công bằng, khách quan, công khai và "
                "minh bạch cho mọi thí sinh."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 7. Nghị định
    ArchiveFixtureDocument(
        document_id="doc_nd_1",
        document_type="Nghị định",
        document_number="84/2026/NĐ-CP",
        title=(
            "Nghị định quy định chi tiết một số điều của Luật Giáo dục về "
            "chế độ chính sách học bổng"
        ),
        issuer="Chính phủ",
        issued_date=date(2026, 4, 15),
        body_lines=(
            "Điều 1. Phạm vi điều chỉnh",
            (
                "Nghị định này quy định về học bổng khuyến khích học tập, học bổng chính sách "
                "và trợ cấp xã hội cho học sinh sinh viên."
            ),
            "Điều 2. Đối tượng được xét cấp học bổng",
            (
                "Học sinh, sinh viên đạt kết quả học tập và rèn luyện từ loại khá trở lên "
                "tại các cơ sở giáo dục nghề nghiệp và đại học."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 8. Same-topic Old (Tuyển sinh mầm non 2024-2025, no supersession link)
    ArchiveFixtureDocument(
        document_id="doc_ts_old",
        document_type="Công văn",
        document_number="08/CV-SGDĐT",
        title="Công văn hướng dẫn công tác tuyển sinh mầm non năm học 2024-2025",
        issuer="Sở Giáo dục và Đào tạo tỉnh Nam Hà",
        issued_date=date(2024, 5, 10),
        body_lines=(
            "Hướng dẫn công tác tuyển sinh trẻ mầm non 5 tuổi năm học 2024-2025.",
            "Đảm bảo 100% trẻ em 5 tuổi được đến trường và chuẩn bị vào lớp 1.",
        ),
        is_current=True,
        version=1,
    ),
    # 9. Same-topic New (Tuyển sinh mầm non 2026-2027, no supersession link)
    ArchiveFixtureDocument(
        document_id="doc_ts_new",
        document_type="Công văn",
        document_number="15/CV-SGDĐT",
        title="Công văn hướng dẫn công tác tuyển sinh mầm non năm học 2026-2027",
        issuer="Sở Giáo dục và Đào tạo tỉnh Nam Hà",
        issued_date=date(2026, 5, 15),
        body_lines=(
            "Hướng dẫn công tác tuyển sinh trẻ mầm non 5 tuổi năm học 2026-2027 trên địa bàn tỉnh.",
            "Thực hiện ứng dụng công nghệ thông tin và đăng ký tuyển sinh trực tuyến toàn diện.",
        ),
        is_current=True,
        version=1,
    ),
    # 10. Cross-reference pair (replaces Quyết định 57/QĐ-UBND)
    ArchiveFixtureDocument(
        document_id="doc_qd_replace",
        document_type="Quyết định",
        document_number="88/QĐ-UBND",
        title=(
            "Quyết định ban hành Quy định mới về chế độ khen thưởng và thay thế "
            "Quyết định số 57/QĐ-UBND"
        ),
        issuer="Ủy ban nhân dân tỉnh Nam Hà",
        issued_date=date(2026, 8, 1),
        body_lines=(
            (
                "Điều 1. Ban hành Quy định tiêu chuẩn xét khen thưởng thi đua "
                "giáo viên và học sinh xuất sắc."
            ),
            (
                "Điều 2. Quyết định này có hiệu lực kể từ ngày ký và thay thế "
                "Quyết định số 57/QĐ-UBND ngày 10 tháng 11 năm 2025 của Ủy ban nhân dân tỉnh."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 11. Hard negative 1: PCCC
    ArchiveFixtureDocument(
        document_id="doc_neg_pccc",
        document_type="Công văn",
        document_number="45/CV-CAT",
        title="Công văn về việc tăng cường công tác phòng cháy chữa cháy tại các cơ sở giáo dục",
        issuer="Công an tỉnh Nam Hà",
        issued_date=date(2026, 2, 20),
        body_lines=(
            "Yêu cầu các cơ sở giáo dục kiểm tra định kỳ hệ thống thiết bị phòng cháy chữa cháy.",
            (
                "Tổ chức tập huấn kỹ năng thoát hiểm và diễn tập chữa cháy "
                "cho toàn thể cán bộ giáo viên."
            ),
        ),
        is_current=True,
        version=1,
    ),
    # 12. Hard negative 2: ATVSTP
    ArchiveFixtureDocument(
        document_id="doc_neg_atvstp",
        document_type="Quyết định",
        document_number="112/QĐ-SYT",
        title="Quyết định thành lập đoàn kiểm tra an toàn vệ sinh thực phẩm bếp ăn bán trú",
        issuer="Sở Y tế tỉnh Nam Hà",
        issued_date=date(2026, 3, 10),
        body_lines=(
            (
                "Điều 1. Thành lập đoàn thanh tra liên ngành kiểm tra an toàn vệ sinh thực phẩm "
                "tại các trường mầm non và tiểu học."
            ),
            ("Điều 2. Đoàn kiểm tra có nhiệm vụ báo cáo kết quả trước ngày 30 tháng 04 năm 2026."),
        ),
        is_current=True,
        version=1,
    ),
    # 13. Hard negative 3: Tài chính
    ArchiveFixtureDocument(
        document_id="doc_neg_qldg",
        document_type="Công văn",
        document_number="73/CV-STC",
        title="Công văn hướng dẫn quản lý tài chính và quyết toán ngân sách chi thường xuyên",
        issuer="Sở Tài chính tỉnh Nam Hà",
        issued_date=date(2026, 4, 1),
        body_lines=(
            (
                "Hướng dẫn các đơn vị sự nghiệp công lập thực hiện lập dự toán và quyết toán "
                "thu chi ngân sách năm 2026."
            ),
            "Thực hiện nghiêm túc chế độ công khai tài chính theo đúng quy định hiện hành.",
        ),
        is_current=True,
        version=1,
    ),
    # 14. Superseded parse version 1 (is_current=False)
    ArchiveFixtureDocument(
        document_id="doc_sup_1",
        document_type="Quyết định",
        document_number="99/QĐ-UBND",
        title="Quyết định phê duyệt danh mục định mức biên chế sự nghiệp giáo dục",
        issuer="Ủy ban nhân dân tỉnh Nam Hà",
        issued_date=date(2026, 5, 1),
        body_lines=(
            (
                "Điều 1. Phê duyệt định mức biên chế tạm thời áp dụng mức phân bổ bí mật cũ "
                "STALE_VERSION_V1_TRAP_PHRASE không còn hiệu lực."
            ),
        ),
        is_current=False,
        version=1,
    ),
    # 15. Current parse version 2 (is_current=True)
    ArchiveFixtureDocument(
        document_id="doc_sup_1",
        document_type="Quyết định",
        document_number="99/QĐ-UBND",
        title="Quyết định phê duyệt danh mục định mức biên chế sự nghiệp giáo dục",
        issuer="Ủy ban nhân dân tỉnh Nam Hà",
        issued_date=date(2026, 5, 1),
        body_lines=(
            (
                "Điều 1. Phê duyệt định mức biên chế chính thức áp dụng cho các cơ sở giáo dục "
                "công lập năm học 2026-2027."
            ),
            (
                "Điều 2. Sở Nội vụ phối hợp Sở Giáo dục và Đào tạo tổ chức tuyển dụng biên chế "
                "theo quy định."
            ),
        ),
        is_current=True,
        version=2,
    ),
)


def build_canonical(doc: ArchiveFixtureDocument) -> CanonicalDocument:
    """Build a synthetic CanonicalDocument from an ArchiveFixtureDocument."""
    run_id = f"run_{doc.document_id}_v{doc.version}"
    blocks = [
        CanonicalBlock(
            id=f"b_{doc.version}_{index:04d}",
            type=BlockType.PARAGRAPH,
            text=line,
            reading_order=index,
            provenance=BlockProvenance(page_number=1),
        )
        for index, line in enumerate(doc.body_lines)
    ]
    return CanonicalDocument(
        document_id=doc.document_id,
        parser_run=ParserRun(
            id=run_id,
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
                raw_value=doc.document_type,
                normalized_value=_normalize_doc_type(doc.document_type),
                extractor=Extractor(name="test", version="1.0"),
            ),
            ExtractedField(
                id="field_document_number",
                name="document_number",
                raw_value=doc.document_number,
                normalized_value=doc.document_number,
                extractor=Extractor(name="test", version="1.0"),
            ),
            ExtractedField(
                id="field_issuer",
                name="issuer",
                raw_value=doc.issuer,
                normalized_value=doc.issuer,
                extractor=Extractor(name="test", version="1.0"),
            ),
            ExtractedField(
                id="field_issue_date",
                name="issue_date",
                raw_value=doc.issued_date.isoformat(),
                normalized_value=doc.issued_date.isoformat(),
                extractor=Extractor(name="test", version="1.0"),
            ),
            ExtractedField(
                id="field_title",
                name="title",
                raw_value=doc.title,
                normalized_value=doc.title,
                extractor=Extractor(name="test", version="1.0"),
            ),
        ],
        quality_report=QualityReport(route="born_digital", route_confidence=0.99),
    )


def seed_archive(
    session_factory: sessionmaker[Session] | Session | Engine | Callable[[], Session],
    *,
    embedding_version: str = "fake-bge-m3-v1",
    dimension: int = 1024,
) -> None:
    """Chunk every corpus document with build_chunks and persist real rows.

    Must write documents, parse_runs (is_current + documents.current_parse_run_id agreeing)
    and document_chunks INCLUDING chunk_metadata and a real embedding vector.
    """
    provider = FakeEmbeddingProvider(dimension=dimension, embedding_version=embedding_version)

    # Find the current parse run id for each document_id
    current_runs: dict[str, str] = {}
    current_docs: dict[str, ArchiveFixtureDocument] = {}
    for doc in ARCHIVE_CORPUS:
        if doc.is_current:
            current_runs[doc.document_id] = f"run_{doc.document_id}_v{doc.version}"
            current_docs[doc.document_id] = doc

    def _seed(session: Session) -> None:
        # Add Document rows
        for doc_id, doc in current_docs.items():
            session.add(
                Document(
                    id=doc_id,
                    filename=f"{doc_id}.pdf",
                    content_type="application/pdf",
                    byte_size=2048,
                    checksum_sha256=doc_id.ljust(64, "0"),
                    storage_uri=f"local://{doc_id}",
                    status="READY",
                    document_type=doc.document_type,
                    document_number=doc.document_number,
                    title=doc.title,
                    issuer=doc.issuer,
                    issued_date=doc.issued_date,
                    current_parse_run_id=current_runs[doc_id],
                    requires_user_review=False,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

        # Add ParseRun and DocumentChunk rows for every fixture (including v1 superseded)
        for doc in ARCHIVE_CORPUS:
            run_id = f"run_{doc.document_id}_v{doc.version}"
            canonical = build_canonical(doc)
            chunks = build_chunks(canonical, document_version=doc.version)

            vectors = asyncio.run(
                provider.embed_documents([chunk.text for chunk in chunks])
            ).vectors

            session.add(
                ParseRun(
                    id=run_id,
                    document_id=doc.document_id,
                    version=doc.version,
                    is_current=doc.is_current,
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
                        embedding_version=embedding_version,
                        created_at=NOW,
                    )
                )

    if isinstance(session_factory, Session):
        _seed(session_factory)
        session_factory.flush()
    elif isinstance(session_factory, Engine):
        with Session(session_factory, expire_on_commit=False) as session:
            with session.begin():
                _seed(session)
    elif callable(session_factory):
        with session_factory() as session:
            with session.begin():
                _seed(session)
    else:
        raise TypeError(f"unsupported session_factory type: {type(session_factory)}")


__all__ = [
    "ARCHIVE_CORPUS",
    "ArchiveFixtureDocument",
    "build_canonical",
    "seed_archive",
]
