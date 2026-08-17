"""PDF inspection and routing.

The router is heuristic on purpose. It emits both a label and the diagnostic signals
that produced it, so routing failures can be understood and measured independently
from parser quality (`docs/03_DOCUMENT_PIPELINE.md` section 10).

PyMuPDF is used here strictly as a low-level PDF inspection utility, which is its
documented role until benchmark evidence promotes it.
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .errors import ParserError, ParserErrorCode

ROUTER_VERSION = "1.0"

# A page needs at least this many extractable characters before its text layer is
# treated as a real text layer rather than stray marks or an OCR-free caption.
MIN_TEXT_LAYER_CHARS = 60

# Fraction of a page's area covered by images before it looks like a scan.
MIN_SCAN_IMAGE_AREA_RATIO = 0.45

# Fraction of suspicious characters before a text layer is called garbled.
GARBLED_CHAR_RATIO = 0.20

# Fraction of pages that must agree before a whole-document label is confident.
DOMINANT_PAGE_RATIO = 0.80

# Inspection runs on untrusted uploads, so it samples rather than reads everything: a
# small crafted PDF can otherwise expand into gigabytes of text and image geometry. The
# route label is a ratio over pages, so a leading sample of this size is representative.
MAX_INSPECTED_PAGES = 50

# Per page, only this many characters feed the garbled-ratio and char-count signals.
# Well above MIN_TEXT_LAYER_CHARS, so classification thresholds are unaffected.
MAX_PAGE_TEXT_CHARS = 20_000

# Per page, only this many images have their placement rectangles resolved.
MAX_INSPECTED_IMAGES_PER_PAGE = 200


class Route(StrEnum):
    BORN_DIGITAL = "born_digital"
    SCANNED = "scanned"
    MIXED = "mixed"
    GARBLED_TEXT_LAYER = "garbled_text_layer"
    ENCRYPTED = "encrypted"
    UNSUPPORTED = "unsupported"


class PageClass(StrEnum):
    TEXT = "text"
    IMAGE_ONLY = "image_only"
    GARBLED = "garbled"
    SPARSE = "sparse"


class PageSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    width: float
    height: float
    rotation: int
    char_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    image_area_ratio: float = Field(ge=0.0, le=1.0)
    garbled_char_ratio: float = Field(ge=0.0, le=1.0)
    has_vietnamese_diacritics: bool
    is_nfc_normalized: bool
    classification: PageClass


class InspectionReport(BaseModel):
    """Router output: the label plus every signal used to reach it."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    router_version: str = ROUTER_VERSION
    route: Route
    route_confidence: float = Field(ge=0.0, le=1.0)
    page_count: int = Field(ge=0)
    encrypted: bool = False
    needs_password: bool = False
    pages: list[PageSignals] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def recommended_parser_capability(self) -> str:
        """Which parser capability the route demands. Not a parser name."""
        if self.route in (Route.SCANNED, Route.GARBLED_TEXT_LAYER):
            return "ocr"
        if self.route == Route.MIXED:
            return "ocr_and_text"
        if self.route == Route.BORN_DIGITAL:
            return "born_digital_text"
        return "none"


# Combining marks Vietnamese actually uses: the five tones plus the letter
# modifiers for â/ê/ô (circumflex), ă (breve) and ơ/ư (horn).
VIETNAMESE_MARKS = frozenset("̛̣̀́̃̉̂̆")

# Vietnamese letters that do not decompose to an ASCII base.
VIETNAMESE_EXTRA_LETTERS = frozenset("Đđ")


def _is_expected_char(char: str) -> bool:
    """Is this character plausible in a Vietnamese administrative document?

    A broken CID font map does not usually produce replacement characters. It
    produces *wrong but real* letters from obscure Latin Extended ranges, which look
    fine to a category check. Checking the actual Vietnamese repertoire catches that
    case; checking Unicode categories does not.
    """
    if char == "�":  # U+FFFD is categorized as a symbol, so check it first
        return False
    if char.isspace() or char in VIETNAMESE_EXTRA_LETTERS:
        return True

    category = unicodedata.category(char)
    if category.startswith(("N", "P", "S", "Z")):
        return True
    if category in ("Co", "Cn") or (category == "Cc" and char not in "\t\n\r"):
        return False

    decomposed = unicodedata.normalize("NFD", char)
    base, marks = decomposed[0], decomposed[1:]
    if not ("a" <= base.lower() <= "z"):
        return False
    return all(mark in VIETNAMESE_MARKS for mark in marks)


def _suspicious_char_ratio(text: str) -> float:
    """Fraction of characters outside the expected Vietnamese/Latin repertoire."""
    if not text:
        return 0.0
    return sum(1 for char in text if not _is_expected_char(char)) / len(text)


def _has_vietnamese_diacritics(text: str) -> bool:
    decomposed = unicodedata.normalize("NFD", text)
    return any(unicodedata.combining(char) for char in decomposed)


def _classify_page(
    char_count: int,
    image_area_ratio: float,
    garbled_char_ratio: float,
) -> PageClass:
    if char_count >= MIN_TEXT_LAYER_CHARS:
        if garbled_char_ratio >= GARBLED_CHAR_RATIO:
            return PageClass.GARBLED
        return PageClass.TEXT
    if image_area_ratio >= MIN_SCAN_IMAGE_AREA_RATIO:
        return PageClass.IMAGE_ONLY
    return PageClass.SPARSE


def _route_from_pages(pages: list[PageSignals]) -> tuple[Route, float, list[str]]:
    warnings: list[str] = []
    if not pages:
        return Route.UNSUPPORTED, 1.0, ["document has no pages"]

    total = len(pages)
    counts = {page_class: 0 for page_class in PageClass}
    for page in pages:
        counts[page.classification] += 1

    text_ratio = counts[PageClass.TEXT] / total
    image_ratio = counts[PageClass.IMAGE_ONLY] / total
    garbled_ratio = counts[PageClass.GARBLED] / total
    sparse_ratio = counts[PageClass.SPARSE] / total

    if garbled_ratio >= 0.5:
        warnings.append("majority of pages have a suspicious text layer; prefer an OCR route")
        return Route.GARBLED_TEXT_LAYER, min(1.0, 0.5 + garbled_ratio / 2), warnings

    if garbled_ratio > 0.0:
        warnings.append(f"{counts[PageClass.GARBLED]} page(s) have a suspicious text layer")

    scan_like_ratio = image_ratio + sparse_ratio

    if text_ratio >= DOMINANT_PAGE_RATIO:
        return Route.BORN_DIGITAL, text_ratio, warnings

    if scan_like_ratio >= DOMINANT_PAGE_RATIO:
        if sparse_ratio > image_ratio:
            warnings.append("pages have neither a text layer nor large images; low confidence")
            return Route.SCANNED, max(0.4, image_ratio), warnings
        return Route.SCANNED, scan_like_ratio, warnings

    if text_ratio > 0.0 and scan_like_ratio > 0.0:
        # An even split is maximally "mixed", so confidence peaks at 50/50.
        return Route.MIXED, min(1.0, 2 * min(text_ratio, scan_like_ratio)), warnings

    warnings.append("no dominant page class; defaulting to the OCR-capable route")
    return Route.SCANNED, 0.4, warnings


class PdfValidation(BaseModel):
    """Cheap upload-time verdict on raw bytes, before anything is persisted."""

    model_config = ConfigDict(extra="forbid")

    is_pdf: bool
    encrypted: bool = False
    page_count: int = 0
    detail: str = ""


PDF_MAGIC = b"%PDF-"


def validate_pdf_bytes(data: bytes) -> PdfValidation:
    """Validate uploaded bytes as a readable, non-encrypted PDF.

    Lives here rather than in the API service so PyMuPDF stays inside the document
    pipeline package, in its documented PDF-utility role.
    """
    import pymupdf

    if not data.startswith(PDF_MAGIC):
        return PdfValidation(is_pdf=False, detail="missing %PDF- header")

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        return PdfValidation(is_pdf=False, detail=f"could not open document: {type(exc).__name__}")

    with document:
        if document.needs_pass:
            return PdfValidation(
                is_pdf=True,
                encrypted=True,
                page_count=document.page_count,
                detail="document is password protected",
            )
        if document.page_count < 1:
            return PdfValidation(is_pdf=False, detail="document has no pages")
        return PdfValidation(is_pdf=True, page_count=document.page_count)


def inspect_pdf(pdf_path: str | Path, document_id: str | None = None) -> InspectionReport:
    """Inspect a PDF and return its route label plus diagnostic signals.

    Never raises for ordinary bad input: encrypted and malformed files are reported as
    routes so the caller can record them as data instead of crashes.
    """
    import pymupdf

    path = Path(pdf_path)
    doc_id = document_id or path.stem

    if not path.is_file():
        raise ParserError(
            ParserErrorCode.UNSUPPORTED_INPUT,
            f"input file not found: {path}",
            parser_name="router",
        )

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # provider-specific failures become structured routes
        return InspectionReport(
            document_id=doc_id,
            route=Route.UNSUPPORTED,
            route_confidence=1.0,
            page_count=0,
            signals={"open_error": type(exc).__name__},
            warnings=[f"could not open document: {exc}"],
        )

    with document:
        if document.needs_pass:
            return InspectionReport(
                document_id=doc_id,
                route=Route.ENCRYPTED,
                route_confidence=1.0,
                page_count=document.page_count,
                encrypted=True,
                needs_password=True,
                signals={"is_encrypted": bool(document.is_encrypted)},
                warnings=["document is password protected; no text layer is readable"],
            )

        if not document.is_pdf:
            return InspectionReport(
                document_id=doc_id,
                route=Route.UNSUPPORTED,
                route_confidence=1.0,
                page_count=document.page_count,
                warnings=["input is not a PDF"],
            )

        pages: list[PageSignals] = []
        inspected_page_count = min(document.page_count, MAX_INSPECTED_PAGES)
        for index in range(inspected_page_count):
            page = document.load_page(index)
            text = page.get_text("text")[:MAX_PAGE_TEXT_CHARS]
            rect = page.rect
            page_area = float(rect.width * rect.height) or 1.0

            image_area = 0.0
            image_count = 0
            for image in page.get_images(full=True)[:MAX_INSPECTED_IMAGES_PER_PAGE]:
                image_count += 1
                for rects in page.get_image_rects(image[0]):
                    image_area += float(rects.width * rects.height)

            image_area_ratio = min(1.0, image_area / page_area)
            garbled_ratio = _suspicious_char_ratio(text)

            pages.append(
                PageSignals(
                    page_number=index + 1,
                    width=float(rect.width),
                    height=float(rect.height),
                    rotation=int(page.rotation),
                    char_count=len(text.strip()),
                    image_count=image_count,
                    image_area_ratio=image_area_ratio,
                    garbled_char_ratio=garbled_ratio,
                    has_vietnamese_diacritics=_has_vietnamese_diacritics(text),
                    is_nfc_normalized=text == unicodedata.normalize("NFC", text),
                    classification=_classify_page(
                        len(text.strip()), image_area_ratio, garbled_ratio
                    ),
                )
            )

        route, confidence, warnings = _route_from_pages(pages)

        if inspected_page_count < document.page_count:
            warnings.append(
                f"routing sampled the first {inspected_page_count} of {document.page_count} pages"
            )

        rotated_pages = [page.page_number for page in pages if page.rotation != 0]
        if rotated_pages:
            warnings.append(f"rotated pages detected: {rotated_pages}")

        non_nfc_pages = [page.page_number for page in pages if not page.is_nfc_normalized]
        if non_nfc_pages:
            warnings.append(f"text layer is not NFC-normalized on pages {non_nfc_pages}")

        total = len(pages) or 1
        signals: dict[str, Any] = {
            "text_page_ratio": sum(p.classification == PageClass.TEXT for p in pages) / total,
            "image_page_ratio": sum(p.classification == PageClass.IMAGE_ONLY for p in pages)
            / total,
            "garbled_page_ratio": sum(p.classification == PageClass.GARBLED for p in pages) / total,
            "sparse_page_ratio": sum(p.classification == PageClass.SPARSE for p in pages) / total,
            "rotated_page_numbers": rotated_pages,
            "rotated_page_count": len(rotated_pages),
            "mean_chars_per_page": sum(p.char_count for p in pages) / total,
            "pages_with_diacritics": sum(p.has_vietnamese_diacritics for p in pages),
            "non_nfc_page_numbers": non_nfc_pages,
            "inspected_page_count": inspected_page_count,
        }

        return InspectionReport(
            document_id=doc_id,
            route=route,
            route_confidence=min(1.0, max(0.0, confidence)),
            page_count=document.page_count,
            encrypted=bool(document.is_encrypted),
            needs_password=False,
            pages=pages,
            signals=signals,
            warnings=warnings,
        )
