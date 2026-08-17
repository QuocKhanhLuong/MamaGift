"""Page preview rendering.

Verification against the original page image is the product's core promise, so
rendering lives beside the pipeline rather than in the API service — PyMuPDF stays in
its documented PDF-utility role and no product code imports a provider directly.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ParserError, ParserErrorCode

DEFAULT_PREVIEW_DPI = 110
MIN_PREVIEW_DPI = 36
MAX_PREVIEW_DPI = 300

# A pixmap is 4 bytes per pixel plus a PNG encode, so an uncapped page rect turns one
# unauthenticated preview request into a multi-gigabyte allocation. 20 MP is the area of
# an A3 page at MAX_PREVIEW_DPI, i.e. beyond anything a real document needs.
MAX_PREVIEW_PIXELS = 20_000_000


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

    resolution = max(MIN_PREVIEW_DPI, min(int(dpi), MAX_PREVIEW_DPI))

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
        try:
            page = document.load_page(page_number - 1)
            rect = page.rect
            scale = resolution / 72.0
            pixels = round(rect.width * scale) * round(rect.height * scale)
            if pixels > MAX_PREVIEW_PIXELS:
                raise ParserError(
                    ParserErrorCode.UNSUPPORTED_INPUT,
                    (
                        f"page {page_number} would render to {pixels} pixels at "
                        f"{resolution} dpi, above the {MAX_PREVIEW_PIXELS} preview limit"
                    ),
                    parser_name="preview",
                    details={
                        "page_number": page_number,
                        "dpi": resolution,
                        "pixels": pixels,
                        "max_pixels": MAX_PREVIEW_PIXELS,
                    },
                )
            pixmap = page.get_pixmap(dpi=resolution)
            png: bytes = pixmap.tobytes("png")
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError(
                ParserErrorCode.INVALID_PDF,
                f"could not render page {page_number}: {exc}",
                parser_name="preview",
            ) from exc
        return png
