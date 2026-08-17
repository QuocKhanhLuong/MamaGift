"""Page preview rendering.

Verification against the original page image is the product's core promise, so
rendering lives beside the pipeline rather than in the API service — PyMuPDF stays in
its documented PDF-utility role and no product code imports a provider directly.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ParserError, ParserErrorCode

DEFAULT_PREVIEW_DPI = 110
MAX_PREVIEW_DPI = 300


def render_page_png(
    pdf_path: str | Path, page_number: int, dpi: int = DEFAULT_PREVIEW_DPI
) -> bytes:
    """Render one 1-based page to PNG bytes."""
    import pymupdf

    path = Path(pdf_path)
    if not path.is_file():
        raise ParserError(
            ParserErrorCode.UNSUPPORTED_INPUT,
            f"input file not found: {path}",
            parser_name="preview",
        )
    if page_number < 1:
        raise ParserError(
            ParserErrorCode.UNSUPPORTED_INPUT,
            "page numbers start at 1",
            parser_name="preview",
        )

    resolution = max(36, min(int(dpi), MAX_PREVIEW_DPI))

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise ParserError(
            ParserErrorCode.INVALID_PDF,
            f"could not open the document: {exc}",
            parser_name="preview",
        ) from exc

    with document:
        if document.needs_pass:
            raise ParserError(
                ParserErrorCode.ENCRYPTED_PDF,
                "document is password protected",
                parser_name="preview",
            )
        if page_number > document.page_count:
            raise ParserError(
                ParserErrorCode.UNSUPPORTED_INPUT,
                f"page {page_number} is out of range (document has {document.page_count})",
                parser_name="preview",
            )
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(dpi=resolution)
        png: bytes = pixmap.tobytes("png")
        return png
