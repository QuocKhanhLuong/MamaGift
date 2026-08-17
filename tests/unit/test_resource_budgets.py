"""Resource budgets for the untrusted-input paths.

Preview rendering, route inspection and header-field matching all run on uploaded
bytes before anyone has vouched for them, so each one is bounded here against a
crafted input rather than trusted to be well behaved.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mamagift_docpipe import ParserError, ParserErrorCode, inspect_pdf
from mamagift_docpipe.admin import patterns as pat
from mamagift_docpipe.preview import MAX_PREVIEW_PIXELS, render_page_png
from mamagift_docpipe.router import MAX_INSPECTED_PAGES, MAX_PAGE_TEXT_CHARS

pytestmark = pytest.mark.unit


def _pdf_with_pages(path: Path, count: int, width: float, height: float, text: str = "") -> Path:
    import pymupdf

    with pymupdf.open() as document:
        for _ in range(count):
            page = document.new_page(width=width, height=height)
            if text:
                page.insert_text((20, 20), text)
        document.save(path)
    return path


def test_oversized_page_is_rejected_before_the_pixmap_is_allocated(tmp_path: Path) -> None:
    pdf = _pdf_with_pages(tmp_path / "huge.pdf", 1, 10_000, 10_000)

    started = time.perf_counter()
    with pytest.raises(ParserError) as excinfo:
        render_page_png(pdf, 1)
    elapsed = time.perf_counter() - started

    assert excinfo.value.code == ParserErrorCode.UNSUPPORTED_INPUT
    assert excinfo.value.model.details["max_pixels"] == MAX_PREVIEW_PIXELS
    assert excinfo.value.model.details["pixels"] > MAX_PREVIEW_PIXELS
    assert elapsed < 1.0


def test_ordinary_page_still_renders(tmp_path: Path) -> None:
    pdf = _pdf_with_pages(tmp_path / "a4.pdf", 1, 595, 842, text="Số: 12/QĐ-UBND")
    assert render_page_png(pdf, 1).startswith(b"\x89PNG")


def test_mupdf_render_failures_become_structured_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pymupdf

    pdf = _pdf_with_pages(tmp_path / "ok.pdf", 1, 595, 842)

    def _explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("mupdf: limit exceeded")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", _explode)

    with pytest.raises(ParserError) as excinfo:
        render_page_png(pdf, 1)

    assert excinfo.value.code == ParserErrorCode.INVALID_PDF
    assert "could not render page 1" in excinfo.value.model.message


def test_inspection_samples_a_bounded_number_of_pages(tmp_path: Path) -> None:
    page_count = MAX_INSPECTED_PAGES * 8
    pdf = _pdf_with_pages(tmp_path / "many.pdf", page_count, 595, 842, text="Điều 1. Nội dung")

    started = time.perf_counter()
    report = inspect_pdf(pdf, document_id="many")
    elapsed = time.perf_counter() - started

    assert report.page_count == page_count
    assert len(report.pages) == MAX_INSPECTED_PAGES
    assert report.signals["inspected_page_count"] == MAX_INSPECTED_PAGES
    assert any("sampled the first" in warning for warning in report.warnings)
    assert elapsed < 10.0


def test_inspection_reads_a_bounded_number_of_characters_per_page(tmp_path: Path) -> None:
    import pymupdf

    pdf = tmp_path / "wall_of_text.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_textbox(
            pymupdf.Rect(0, 0, 595, 842), "Điều khoản thi hành. " * 20_000, fontsize=1
        )
        document.save(pdf)

    report = inspect_pdf(pdf, document_id="wall")

    assert report.pages[0].char_count <= MAX_PAGE_TEXT_CHARS


def test_number_pattern_stays_fast_on_adversarial_whitespace() -> None:
    """U+3000 survives `normalize_text`, so the header patterns must bound it themselves."""
    # A separator after the run makes the capture group fail, which is what forces the
    # back-to-back `\s*` groups to backtrack quadratically.
    line = "Số" + "　" * 8_000 + ";"

    started = time.perf_counter()
    for _ in range(10):
        pat.NUMBER_RE.match(line)
        pat.NUMBER_INLINE_RE.search(line)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1


def test_number_pattern_still_matches_real_header_lines() -> None:
    match = pat.NUMBER_RE.match("Số: 1234/UBND-VP")
    assert match is not None and match.group(1) == "1234/UBND-VP"

    inline = pat.NUMBER_INLINE_RE.search("Kính gửi các đơn vị, Số: 57/QĐ-UBND ngày 3")
    assert inline is not None and inline.group(1) == "57/QĐ-UBND"
