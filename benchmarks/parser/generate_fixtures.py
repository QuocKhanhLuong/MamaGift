"""Generate the sanitized synthetic benchmark fixture corpus.

Every fixture is invented. No real school or family document is ever used
(`docs/03_DOCUMENT_PIPELINE.md` section 3.1). The names, numbers, dates and people in
these files do not refer to anything real.

Ground truth is written from the same authored document definition that produces the
PDF, never from parser output. Deriving expected values from a parser would make the
benchmark score itself.

Run with:

    uv run python benchmarks/parser/generate_fixtures.py

Regenerating is deterministic: identical input definitions produce identical PDFs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
GROUND_TRUTH = Path(__file__).parent / "ground_truth"
MANIFEST = Path(__file__).parent / "manifest.jsonl"

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
LEFT_MARGIN = 72.0
BODY_FONT_SIZE = 11.0
LINE_GAP = 26.0

# Header/footer bands must sit inside the normalizer's 7% margin band so the
# header/footer leakage metric has something real to measure.
HEADER_Y = 40.0
FOOTER_Y = 812.0

ENCRYPTED_USER_PASSWORD = "mamagift-fixture"  # documented, non-secret fixture password

BlockKind = Literal["header", "footer", "body", "heading", "title", "list_item"]


@dataclass
class AuthoredBlock:
    kind: BlockKind
    text: str
    bold: bool = False


@dataclass
class AuthoredPage:
    blocks: list[AuthoredBlock] = field(default_factory=list)
    rotation: int = 0


@dataclass
class AuthoredDocument:
    document_id: str
    route_label: str
    difficulty: str
    notes: str
    pages: list[AuthoredPage]
    critical_fields: dict[str, str] = field(default_factory=dict)
    lists: list[list[str]] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    write_ground_truth: bool = True


def _font() -> pymupdf.Font:
    # Noto Sans covers the full Vietnamese repertoire including stacked diacritics.
    return pymupdf.Font("notos")


def _layout_y(index: int, total_body_blocks: int) -> float:
    del total_body_blocks
    return 110.0 + index * LINE_GAP


MAX_LINE_WIDTH = PAGE_WIDTH - 2 * LEFT_MARGIN


def render_document(doc: AuthoredDocument) -> pymupdf.Document:
    pdf = pymupdf.open()
    font = _font()

    for authored_page in doc.pages:
        for block in authored_page.blocks:
            width = font.text_length(block.text, fontsize=BODY_FONT_SIZE)
            if width > MAX_LINE_WIDTH:
                raise ValueError(
                    f"{doc.document_id}: line is {width:.0f}pt wide, exceeds "
                    f"{MAX_LINE_WIDTH:.0f}pt and would be clipped off the page: {block.text!r}"
                )

    for authored_page in doc.pages:
        page = pdf.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_font(fontname="notos", fontbuffer=font.buffer)

        body_index = 0
        body_blocks = [
            block for block in authored_page.blocks if block.kind not in ("header", "footer")
        ]

        for block in authored_page.blocks:
            if block.kind == "header":
                y = HEADER_Y
            elif block.kind == "footer":
                y = FOOTER_Y
            else:
                y = _layout_y(body_index, len(body_blocks))
                body_index += 1

            page.insert_text(
                (LEFT_MARGIN, y),
                block.text,
                fontname="notos",
                fontsize=BODY_FONT_SIZE,
            )

        if authored_page.rotation:
            page.set_rotation(authored_page.rotation)

    return pdf


def ground_truth_for(doc: AuthoredDocument) -> dict[str, object]:
    """Build the ground-truth payload from the authored definition."""
    transcript: dict[str, str] = {}
    reading_order: list[str] = []
    headings: list[dict[str, object]] = []
    header_footer: list[str] = []

    for page_number, page in enumerate(doc.pages, start=1):
        ordered = (
            [block for block in page.blocks if block.kind == "header"]
            + [block for block in page.blocks if block.kind not in ("header", "footer")]
            + [block for block in page.blocks if block.kind == "footer"]
        )
        transcript[str(page_number)] = "\n".join(block.text for block in ordered)

        for block in ordered:
            if block.kind in ("header", "footer"):
                header_footer.append(block.text)
                continue
            reading_order.append(block.text)
            if block.kind == "title":
                headings.append({"level": 1, "text": block.text})
            elif block.kind == "heading":
                headings.append({"level": 2, "text": block.text})

    return {
        "document_id": doc.document_id,
        "page_count": len(doc.pages),
        "critical_fields": doc.critical_fields,
        "reading_order": reading_order,
        "headings": headings,
        "lists": doc.lists,
        "tables": doc.tables,
        "header_footer_texts": header_footer,
        "transcript": transcript,
    }


# --------------------------------------------------------------------- documents


def cong_van() -> AuthoredDocument:
    page_one = AuthoredPage(
        blocks=[
            AuthoredBlock("header", "Công văn số 1234/UBND-VP"),
            AuthoredBlock("body", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            AuthoredBlock("body", "Số: 1234/UBND-VP"),
            AuthoredBlock("body", "Mai Giang, ngày 14 tháng 8 năm 2026"),
            AuthoredBlock("title", "V/v hướng dẫn nộp hồ sơ tuyển sinh năm học 2026-2027"),
            AuthoredBlock("body", "Kính gửi: Hiệu trưởng các trường tiểu học trong xã."),
            AuthoredBlock(
                "body",
                "Thực hiện kế hoạch tuyển sinh, Ủy ban nhân dân xã đề nghị các đơn vị triển khai:",
            ),
            AuthoredBlock("list_item", "1. Niêm yết công khai chỉ tiêu tuyển sinh."),
            AuthoredBlock("list_item", "2. Tiếp nhận hồ sơ trực tiếp và trực tuyến."),
            AuthoredBlock("list_item", "3. Báo cáo kết quả tiếp nhận hồ sơ về Văn phòng."),
            AuthoredBlock("footer", "Trang 1/2"),
        ]
    )
    page_two = AuthoredPage(
        blocks=[
            AuthoredBlock("header", "Công văn số 1234/UBND-VP"),
            AuthoredBlock(
                "body",
                "Báo cáo gửi về Văn phòng trước ngày 25 tháng 8 năm 2026.",
            ),
            AuthoredBlock("body", "Đề nghị các đơn vị nghiêm túc thực hiện."),
            AuthoredBlock("heading", "Nơi nhận:"),
            AuthoredBlock("body", "- Như trên;"),
            AuthoredBlock("body", "- Lưu: VT, VP."),
            AuthoredBlock("body", "KT. CHỦ TỊCH"),
            AuthoredBlock("body", "PHÓ CHỦ TỊCH"),
            AuthoredBlock("body", "Trần Thị Bình"),
            AuthoredBlock("footer", "Trang 2/2"),
        ]
    )
    return AuthoredDocument(
        document_id="cong_van_born_digital",
        route_label="born_digital",
        difficulty="easy",
        notes="Clean born-digital official letter with running header/footer and a numbered list.",
        pages=[page_one, page_two],
        critical_fields={
            "document_number": "1234/UBND-VP",
            "issue_date": "2026-08-14",
            "deadline": "2026-08-25",
            "issuer": "ỦY BAN NHÂN DÂN XÃ MAI GIANG",
            "title": "hướng dẫn nộp hồ sơ tuyển sinh năm học 2026-2027",
        },
        lists=[
            [
                "1. Niêm yết công khai chỉ tiêu tuyển sinh.",
                "2. Tiếp nhận hồ sơ trực tiếp và trực tuyến.",
                "3. Báo cáo kết quả tiếp nhận hồ sơ về Văn phòng.",
            ]
        ],
    )


def quyet_dinh() -> AuthoredDocument:
    page_one = AuthoredPage(
        blocks=[
            AuthoredBlock("header", "Quyết định số 57/QĐ-UBND"),
            AuthoredBlock("body", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            AuthoredBlock("body", "Số: 57/QĐ-UBND"),
            AuthoredBlock("body", "Mai Giang, ngày 03 tháng 3 năm 2026"),
            AuthoredBlock("title", "V/v ban hành quy chế quản lý hồ sơ hành chính"),
            AuthoredBlock("heading", "Chương I. QUY ĐỊNH CHUNG"),
            AuthoredBlock("heading", "Điều 1. Phạm vi điều chỉnh"),
            AuthoredBlock(
                "body",
                "Quyết định này quy định việc lập và lưu trữ hồ sơ hành chính.",
            ),
            AuthoredBlock("heading", "Điều 2. Đối tượng áp dụng"),
            AuthoredBlock("list_item", "1. Các phòng chuyên môn thuộc Ủy ban."),
            AuthoredBlock("list_item", "2. Các đơn vị sự nghiệp trực thuộc."),
            AuthoredBlock("footer", "Trang 1/2"),
        ]
    )
    page_two = AuthoredPage(
        blocks=[
            AuthoredBlock("header", "Quyết định số 57/QĐ-UBND"),
            AuthoredBlock("heading", "Điều 3. Hiệu lực thi hành"),
            AuthoredBlock(
                "body",
                "Quyết định có hiệu lực từ ngày ký. Rà soát trước ngày 30 tháng 4 năm 2026.",
            ),
            AuthoredBlock("heading", "Phụ lục I. Danh mục hồ sơ"),
            AuthoredBlock("body", "STT | Tên hồ sơ | Thời hạn lưu"),
            AuthoredBlock("body", "1 | Hồ sơ tuyển sinh | 05 năm"),
            AuthoredBlock("body", "2 | Hồ sơ thi đua | 10 năm"),
            AuthoredBlock("heading", "Nơi nhận:"),
            AuthoredBlock("body", "- Lưu: VT."),
            AuthoredBlock("footer", "Trang 2/2"),
        ]
    )
    return AuthoredDocument(
        document_id="quyet_dinh_dieu_khoan",
        route_label="born_digital",
        difficulty="medium",
        notes="Decision with Chương/Điều hierarchy, an appendix and a pipe-delimited table.",
        pages=[page_one, page_two],
        critical_fields={
            "document_number": "57/QĐ-UBND",
            "issue_date": "2026-03-03",
            "deadline": "2026-04-30",
            "issuer": "ỦY BAN NHÂN DÂN XÃ MAI GIANG",
            "title": "ban hành quy chế quản lý hồ sơ hành chính",
        },
        lists=[
            [
                "1. Các phòng chuyên môn thuộc Ủy ban.",
                "2. Các đơn vị sự nghiệp trực thuộc.",
            ]
        ],
        tables=[
            {
                "page_number": 2,
                "cells": [
                    ["STT", "Tên hồ sơ", "Thời hạn lưu"],
                    ["1", "Hồ sơ tuyển sinh", "05 năm"],
                    ["2", "Hồ sơ thi đua", "10 năm"],
                ],
            }
        ],
    )


def rotated() -> AuthoredDocument:
    page = AuthoredPage(
        blocks=[
            AuthoredBlock("body", "ỦY BAN NHÂN DÂN XÃ MAI GIANG"),
            AuthoredBlock("body", "Số: 88/TB-UBND"),
            AuthoredBlock("body", "Mai Giang, ngày 09 tháng 9 năm 2026"),
            AuthoredBlock("title", "V/v thông báo lịch tiếp công dân"),
            AuthoredBlock("body", "Lịch tiếp công dân niêm yết tại trụ sở."),
        ],
        rotation=90,
    )
    return AuthoredDocument(
        document_id="trang_xoay",
        route_label="born_digital",
        difficulty="medium",
        notes="Born-digital page stored with a 90-degree rotation flag.",
        pages=[page],
        critical_fields={
            "document_number": "88/TB-UBND",
            "issue_date": "2026-09-09",
            "issuer": "ỦY BAN NHÂN DÂN XÃ MAI GIANG",
            "title": "thông báo lịch tiếp công dân",
        },
    )


def garbled() -> AuthoredDocument:
    """A text layer that decodes to mojibake, as broken CID font maps produce."""
    broken = "�" * 8
    page = AuthoredPage(
        blocks=[
            AuthoredBlock("body", f"{broken} ban {broken} dan {broken}"),
            AuthoredBlock("body", f"S{broken}: 45/{broken}-UBND"),
            AuthoredBlock("body", f"{broken} {broken} {broken} 2026 {broken}"),
            AuthoredBlock("body", f"{broken} {broken} {broken} {broken}"),
            AuthoredBlock("body", f"{broken} ho so {broken} {broken}"),
        ]
    )
    return AuthoredDocument(
        document_id="text_layer_hong",
        route_label="garbled_text_layer",
        difficulty="hard",
        notes="Suspicious text layer; the router must send this to an OCR route.",
        pages=[page],
        write_ground_truth=False,
    )


def _render_scan_page(pdf: pymupdf.Document, source_page: pymupdf.Page) -> None:
    """Insert a rasterized page image with no text layer, imitating a scan."""
    pixmap = source_page.get_pixmap(dpi=110)
    page = pdf.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), pixmap=pixmap)


def write_scanned(source: pymupdf.Document, path: Path, page_indexes: list[int]) -> None:
    pdf = pymupdf.open()
    for index in page_indexes:
        _render_scan_page(pdf, source.load_page(index))
    pdf.save(path, garbage=4, deflate=True)
    pdf.close()


def write_mixed(source: pymupdf.Document, path: Path) -> None:
    """Page 1 keeps its text layer, page 2 is a rasterized scan."""
    pdf = pymupdf.open()
    pdf.insert_pdf(source, from_page=0, to_page=0)
    _render_scan_page(pdf, source.load_page(1))
    pdf.save(path, garbage=4, deflate=True)
    pdf.close()


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH.mkdir(parents=True, exist_ok=True)

    manifest_lines: list[dict[str, object]] = []
    documents = [cong_van(), quyet_dinh(), rotated(), garbled()]

    rendered: dict[str, pymupdf.Document] = {}
    for doc in documents:
        pdf = render_document(doc)
        path = FIXTURES / f"{doc.document_id}.pdf"
        # Subsetting keeps the committed fixtures small; the full Noto face would
        # embed ~250 KiB of glyphs per file.
        pdf.subset_fonts()
        pdf.save(path, garbage=4, deflate=True)
        rendered[doc.document_id] = pymupdf.open(path)
        pdf.close()

        ground_truth_path: str | None = None
        if doc.write_ground_truth:
            ground_truth_path = f"benchmarks/parser/ground_truth/{doc.document_id}.json"
            (GROUND_TRUTH / f"{doc.document_id}.json").write_text(
                json.dumps(ground_truth_for(doc), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        manifest_lines.append(
            {
                "document_id": doc.document_id,
                "path": f"benchmarks/parser/fixtures/{doc.document_id}.pdf",
                "route_label": doc.route_label,
                "difficulty": doc.difficulty,
                "provenance": "synthetic",
                "ground_truth": ground_truth_path,
                "notes": doc.notes,
            }
        )

    source = rendered["cong_van_born_digital"]

    write_scanned(source, FIXTURES / "scan_khong_co_text.pdf", [0, 1])
    manifest_lines.append(
        {
            "document_id": "scan_khong_co_text",
            "path": "benchmarks/parser/fixtures/scan_khong_co_text.pdf",
            "route_label": "scanned",
            "difficulty": "medium",
            "provenance": "synthetic",
            "ground_truth": None,
            "notes": "Rasterized pages with no text layer; requires the OCR route.",
        }
    )

    write_mixed(source, FIXTURES / "ho_so_hon_hop.pdf")
    manifest_lines.append(
        {
            "document_id": "ho_so_hon_hop",
            "path": "benchmarks/parser/fixtures/ho_so_hon_hop.pdf",
            "route_label": "mixed",
            "difficulty": "hard",
            "provenance": "synthetic",
            "ground_truth": None,
            "notes": "Page 1 born-digital, page 2 scanned.",
        }
    )

    encrypted = pymupdf.open(FIXTURES / "cong_van_born_digital.pdf")
    encrypted.save(
        FIXTURES / "tai_lieu_ma_hoa.pdf",
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=ENCRYPTED_USER_PASSWORD,
        owner_pw=ENCRYPTED_USER_PASSWORD,
    )
    encrypted.close()
    manifest_lines.append(
        {
            "document_id": "tai_lieu_ma_hoa",
            "path": "benchmarks/parser/fixtures/tai_lieu_ma_hoa.pdf",
            "route_label": "encrypted",
            "difficulty": "hard",
            "provenance": "synthetic",
            "ground_truth": None,
            "notes": f"Password protected with the documented fixture password "
            f"'{ENCRYPTED_USER_PASSWORD}'.",
        }
    )

    (FIXTURES / "tep_khong_hop_le.pdf").write_bytes(
        b"%PDF-1.7\nthis file is deliberately truncated and has no xref table\n"
    )
    manifest_lines.append(
        {
            "document_id": "tep_khong_hop_le",
            "path": "benchmarks/parser/fixtures/tep_khong_hop_le.pdf",
            "route_label": "unsupported",
            "difficulty": "hard",
            "provenance": "synthetic",
            "ground_truth": None,
            "notes": "Malformed PDF; the router must report it instead of crashing.",
        }
    )

    for document in rendered.values():
        document.close()

    MANIFEST.write_text(
        "".join(
            json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in manifest_lines
        ),
        encoding="utf-8",
    )

    print(f"Wrote {len(manifest_lines)} fixtures to {FIXTURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
