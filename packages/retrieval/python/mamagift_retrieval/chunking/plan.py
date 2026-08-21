"""Deterministic 'Kế hoạch' (plan) structure detector for chunking.

Vietnamese plan documents are not covered by the legal `Chương/Mục/Điều/Khoản/Điểm`
hierarchy `parse_admin_document` builds; their real structure is
`major section -> subsection/task -> child content`, with each task carrying its
own responsible unit, coordinating unit and deadline. Getting the scoping of that
per-task metadata right — never letting Task B's deadline attach to Task A — is the
specific failure this module exists to prevent.

Matching is line-anchored and bounded, in the same conservative style as
`mamagift_docpipe.admin.patterns`: an unrecognised line becomes task/section body
text, never a guessed structural marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from mamagift_docpipe import BlockType, CanonicalDocument
from mamagift_docpipe.admin import patterns as admin_pat

from ..chunk import Chunk, ChunkType
from ._shared import field_value

_FURNITURE_TYPES = frozenset({BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER})

PLAN_SECTION_RE = re.compile(r"^(?:PHẦN\s+)?([IVXLCDM]+)\s*[.)]\s+(.+)$")
PLAN_TASK_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\s*[.)]\s+(.+)$")

OWNER_RE = re.compile(r"^(?:Đơn vị chủ trì|Chủ trì|Cơ quan chủ trì)\s*[:.]?\s*(.+)$", re.IGNORECASE)
COORDINATOR_RE = re.compile(
    r"^(?:Đơn vị phối hợp|Phối hợp|Cơ quan phối hợp)\s*[:.]?\s*(.+)$", re.IGNORECASE
)
DEADLINE_RE = re.compile(
    r"^(?:Thời hạn hoàn thành|Thời hạn|Hạn hoàn thành|Hoàn thành trước|Deadline)"
    r"\s*[:.]?\s*(.+)$",
    re.IGNORECASE,
)


@dataclass
class _TaskState:
    chunk_id: str
    section_chunk_id: str | None
    section_path: list[str]
    ordinal: str
    title: str
    owner: str | None = None
    coordinating_unit: str | None = None
    deadline_raw: str | None = None
    deadline: str | None = None
    body_lines: list[str] = dataclass_field(default_factory=list)
    heading_block_ids: list[str] = dataclass_field(default_factory=list)
    heading_pages: set[int] = dataclass_field(default_factory=set)
    content_block_ids: list[str] = dataclass_field(default_factory=list)
    content_pages: set[int] = dataclass_field(default_factory=set)


def build_plan_chunks(
    document: CanonicalDocument,
    *,
    document_version: int | None = None,
) -> list[Chunk]:
    """Build `plan_section -> plan_task -> child content` chunks for a `Kế hoạch`.

    Returns an empty list for any document whose extracted `document_type` is not
    `ke_hoach`: this builder is deliberately scoped to plans, never guessing plan
    structure onto a document type it was not designed for.
    """
    if field_value(document, "document_type") != "ke_hoach":
        return []

    doc_id, run_id = document.document_id, document.parser_run.id
    doc_type = field_value(document, "document_type")
    doc_number = field_value(document, "document_number")
    issuer = field_value(document, "issuer")
    issued_date = field_value(document, "issue_date")

    section_chunks: list[Chunk] = []
    tasks: list[_TaskState] = []
    section_id: str | None = None
    section_path: list[str] = []
    section_index = 0
    task_index = 0
    task: _TaskState | None = None

    def flush_task() -> None:
        nonlocal task
        if task is not None:
            tasks.append(task)
        task = None

    for page in document.pages:
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            if block.type in _FURNITURE_TYPES:
                continue
            for raw_line in block.text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                section_match = PLAN_SECTION_RE.match(line)
                if section_match:
                    flush_task()
                    section_index += 1
                    label_value, title = section_match.group(1), section_match.group(2).strip()
                    section_id = f"chunk_{doc_id}_{run_id}_plan_section_{section_index:02d}"
                    section_path = [f"{label_value}. {title}"]
                    section_chunks.append(
                        Chunk(
                            chunk_id=section_id,
                            parent_chunk_id=None,
                            document_id=doc_id,
                            parse_run_id=run_id,
                            document_version=document_version,
                            document_type=doc_type,
                            document_number=doc_number,
                            issuer=issuer,
                            issued_date=issued_date,
                            section_path=section_path,
                            chunk_type=ChunkType.PLAN_SECTION,
                            text=title,
                            source_block_ids=[block.id],
                            source_page_numbers=[page.page_number],
                            metadata={"ordinal": label_value},
                        )
                    )
                    continue

                task_match = PLAN_TASK_RE.match(line)
                if task_match:
                    flush_task()
                    task_index += 1
                    ordinal, title = task_match.group(1), task_match.group(2).strip()
                    task = _TaskState(
                        chunk_id=f"chunk_{doc_id}_{run_id}_plan_task_{task_index:03d}",
                        section_chunk_id=section_id,
                        section_path=[*section_path, f"{ordinal}. {title}"],
                        ordinal=ordinal,
                        title=title,
                    )
                    task.heading_block_ids.append(block.id)
                    task.heading_pages.add(page.page_number)
                    continue

                if task is None:
                    # Body text before any task started (a section preamble) belongs to
                    # no task's scope; the fallback chunker picks it up separately.
                    continue

                owner_match = OWNER_RE.match(line)
                if owner_match:
                    task.owner = owner_match.group(1).strip()
                    task.heading_block_ids.append(block.id)
                    task.heading_pages.add(page.page_number)
                    continue

                coordinator_match = COORDINATOR_RE.match(line)
                if coordinator_match:
                    task.coordinating_unit = coordinator_match.group(1).strip()
                    task.heading_block_ids.append(block.id)
                    task.heading_pages.add(page.page_number)
                    continue

                deadline_match = DEADLINE_RE.match(line)
                if deadline_match:
                    raw = deadline_match.group(1).strip()
                    task.deadline_raw = raw
                    parsed = admin_pat.parse_vietnamese_date(raw)
                    task.deadline = parsed[1] if parsed else None
                    task.heading_block_ids.append(block.id)
                    task.heading_pages.add(page.page_number)
                    continue

                task.body_lines.append(line)
                task.content_block_ids.append(block.id)
                task.content_pages.add(page.page_number)

    flush_task()

    task_chunks: list[Chunk] = []
    for item in tasks:
        task_chunks.append(
            Chunk(
                chunk_id=item.chunk_id,
                parent_chunk_id=item.section_chunk_id,
                document_id=doc_id,
                parse_run_id=run_id,
                document_version=document_version,
                document_type=doc_type,
                document_number=doc_number,
                issuer=issuer,
                issued_date=issued_date,
                section_path=item.section_path,
                chunk_type=ChunkType.PLAN_TASK,
                text=item.title,
                source_block_ids=list(dict.fromkeys(item.heading_block_ids)),
                source_page_numbers=sorted(item.heading_pages),
                metadata={
                    "ordinal": item.ordinal,
                    "owner": item.owner,
                    "coordinating_unit": item.coordinating_unit,
                    "deadline_raw": item.deadline_raw,
                    "deadline": item.deadline,
                },
            )
        )
        if item.body_lines:
            task_chunks.append(
                Chunk(
                    chunk_id=f"{item.chunk_id}_content",
                    parent_chunk_id=item.chunk_id,
                    document_id=doc_id,
                    parse_run_id=run_id,
                    document_version=document_version,
                    document_type=doc_type,
                    document_number=doc_number,
                    issuer=issuer,
                    issued_date=issued_date,
                    section_path=item.section_path,
                    chunk_type=ChunkType.PARAGRAPH,
                    text="\n".join(item.body_lines),
                    source_block_ids=list(dict.fromkeys(item.content_block_ids)),
                    source_page_numbers=sorted(item.content_pages),
                    metadata={},
                )
            )

    return section_chunks + task_chunks
