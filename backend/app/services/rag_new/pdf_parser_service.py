import logging
import os
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)


class PdfParseError(Exception):
    """Raised when a PDF cannot be read or parsed."""


@dataclass
class PdfPage:
    page_number: int
    extracted_text: str


@dataclass
class ParsedPdf:
    pages: list[PdfPage] = field(default_factory=list)
    total_pages: int = 0


def _is_fragmented(text: str) -> bool:
    """Heuristic: detect if extracted text is broken into single-word lines.

    pypdf sometimes produces output where every word is on its own line.
    We detect this by checking what fraction of non-empty lines are <= 3 chars.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 5:
        return False
    short_lines = sum(1 for ln in lines if len(ln.strip()) <= 3)
    return short_lines / len(lines) > 0.4


def _merge_fragmented_lines(text: str) -> str:
    """Merge single-word / very short lines back into coherent paragraphs.

    When pypdf breaks text into word-per-line output, this reconstructs
    readable paragraphs by joining short consecutive lines.
    """
    raw_lines = text.splitlines()
    if not raw_lines:
        return text

    merged: list[str] = []
    buffer: list[str] = []

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            # Blank line = paragraph boundary
            if buffer:
                merged.append(" ".join(buffer))
                buffer = []
            merged.append("")  # preserve paragraph break
            continue

        # If the line is very short (likely a fragment), buffer it
        if len(stripped) <= 3 and not stripped[-1] in ".!?":
            buffer.append(stripped)
        else:
            # Substantial line — flush buffer and add this line
            if buffer:
                merged.append(" ".join(buffer))
                buffer = []
            merged.append(stripped)

    if buffer:
        merged.append(" ".join(buffer))

    return "\n".join(merged)


def _is_multicolumn(text: str) -> bool:
    """Heuristic: detect if text has multi-column layout based on line lengths.

    Multi-column PDFs produce lines with large horizontal gaps that, when
    concatenated, create very long lines interspersed with short ones. A high
    variance in line lengths relative to the median is a signal.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 6:
        return False
    lengths = [len(ln) for ln in lines]
    median = sorted(lengths)[len(lengths) // 2]
    if median == 0:
        return False
    # If many lines are far from the median (>2x shorter), likely multi-column
    far_from_median = sum(1 for l in lengths if l < median * 0.3)
    return far_from_median / len(lengths) > 0.3


def _merge_multicolumn(text: str) -> str:
    """Reorder multi-column text into single-column reading order.

    Uses a simple heuristic: if lines alternate between long and short,
    sort by estimated reading position. For two-column layouts, lines in
    the right column tend to start with more whitespace or have a
    characteristic x-offset pattern. Since we don't have coordinates from
    plain text, we sort by length bands to approximate reading order.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return text

    lengths = [len(ln) for ln in lines]
    median = sorted(lengths)[len(lengths) // 2]

    left_col: list[str] = []
    right_col: list[str] = []

    for line in lines:
        if len(line) <= median:
            left_col.append(line)
        else:
            right_col.append(line)

    # Interleave: left column first, then right column
    merged = left_col + right_col
    return "\n".join(merged)


def _needs_ocr(text: str) -> bool:
    """Heuristic: detect if extracted text is too sparse for a real document.

    Image-only PDFs or those with embedded fonts that can't be extracted
    produce very little text. If the average chars per page is < 50, OCR
    is likely needed.
    """
    if not text.strip():
        return True
    chars_per_line = len(text.strip()) / max(1, len(text.splitlines()))
    return chars_per_line < 10 and len(text.strip()) < 200


class PdfParserService:

    def parse(self, file_path: str) -> ParsedPdf:
        """Parse a PDF file page by page, returning extracted text per page.

        Uses pdfplumber (layout-aware) as primary extractor, with pypdf as
        fallback. Falls back to OCR (pytesseract) when the text extractors
        produce too little text. Multi-column layouts are detected and
        reordered into reading order.
        """
        if not os.path.isfile(file_path):
            raise PdfParseError(f"PDF file not found: {file_path}")

        try:
            pages = self._parse_with_pdfplumber(file_path)
        except Exception as exc:
            logger.warning("pdfplumber failed (%s), falling back to pypdf", exc)
            try:
                pages = self._parse_with_pypdf(file_path)
            except Exception as exc2:
                raise PdfParseError(
                    f"Failed to parse PDF '{file_path}'"
                ) from exc2

        if not pages:
            raise PdfParseError(f"PDF '{file_path}' has no readable pages")

        # Post-process: OCR fallback and multi-column reordering
        pages = self._postprocess_pages(pages, file_path)

        return ParsedPdf(pages=pages, total_pages=len(pages))

    def _postprocess_pages(
        self, pages: list[PdfPage], file_path: str
    ) -> list[PdfPage]:
        """Apply OCR fallback and multi-column reordering to parsed pages."""
        processed: list[PdfPage] = []
        ocr_available = self._check_ocr_available() and settings.ocr_enabled

        if not settings.ocr_enabled:
            logger.info("OCR is disabled via OCR_ENABLED=False; skipping OCR fallback")

        for page in pages:
            text = page.extracted_text

            # OCR fallback when text is too sparse
            if _needs_ocr(text) and ocr_available:
                logger.info(
                    "Page %d has sparse text (%d chars), attempting OCR",
                    page.page_number,
                    len(text),
                )
                ocr_text = self._ocr_page(file_path, page.page_number)
                if ocr_text and len(ocr_text) > len(text):
                    text = ocr_text

            # Multi-column reordering
            if _is_multicolumn(text):
                logger.debug(
                    "Page %d detected as multi-column, reordering",
                    page.page_number,
                )
                text = _merge_multicolumn(text)

            processed.append(PdfPage(page_number=page.page_number, extracted_text=text))

        return processed

    @staticmethod
    def _check_ocr_available() -> bool:
        """Check if pytesseract and pdf2image are available."""
        try:
            import pytesseract  # noqa: F401
            from pdf2image import convert_from_path  # noqa: F401

            return True
        except ImportError:
            return False

    def _ocr_page(self, file_path: str, page_number: int) -> str:
        """Extract text from a single page using OCR.

        Renders one page at a time at reduced DPI and explicitly releases
        the image object to bound memory usage on constrained instances.
        """
        try:
            from pdf2image import convert_from_path
            import pytesseract

            images = convert_from_path(
                file_path,
                first_page=page_number,
                last_page=page_number,
                dpi=settings.ocr_dpi,
            )
            if not images:
                return ""
            text = pytesseract.image_to_string(images[0])
            # Explicitly release the image object to free RAM promptly
            images[0].close()
            del images
            return text.strip() if text else ""
        except Exception as exc:
            logger.warning(
                "OCR failed for page %d of %s: %s",
                page_number,
                file_path,
                exc,
            )
            return ""

    # ------------------------------------------------------------------ #
    # pdfplumber (primary)
    # ------------------------------------------------------------------ #

    def _parse_with_pdfplumber(self, file_path: str) -> list[PdfPage]:
        import pdfplumber

        pages: list[PdfPage] = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""

                # Also extract tables and append them so they aren't lost
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if row:
                                cells = [str(c).strip() if c else "" for c in row]
                                text += "\n" + " | ".join(cells)

                # Fix fragmented output from poorly structured PDFs
                if _is_fragmented(text):
                    logger.debug(
                        "Page %d output is fragmented, merging lines", page_num
                    )
                    text = _merge_fragmented_lines(text)

                pages.append(PdfPage(page_number=page_num, extracted_text=text))

        return pages

    # ------------------------------------------------------------------ #
    # pypdf (fallback)
    # ------------------------------------------------------------------ #

    def _parse_with_pypdf(self, file_path: str) -> list[PdfPage]:
        from pypdf import PdfReader

        pages: list[PdfPage] = []
        with open(file_path, "rb") as fh:
            reader = PdfReader(fh)
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""

                if _is_fragmented(text):
                    logger.debug(
                        "pypdf page %d output is fragmented, merging lines",
                        page_num,
                    )
                    text = _merge_fragmented_lines(text)

                pages.append(PdfPage(page_number=page_num, extracted_text=text))

        return pages
