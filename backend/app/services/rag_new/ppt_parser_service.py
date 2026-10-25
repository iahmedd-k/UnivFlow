from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.pdf_parser_service import ParsedPdf, PdfPage

logger = logging.getLogger(__name__)


class PptParseError(Exception):
    """Raised when a PowerPoint file cannot be read or parsed."""


@dataclass
class PptParserService:
    """Parse PowerPoint (.pptx) files into ParsedPdf format.

    Each slide becomes a separate page. Slide content (text, tables, notes)
    is extracted and rendered as structured text.
    """

    def parse(self, file_path: str) -> ParsedPdf:
        """Parse a .pptx file and return ParsedPdf."""
        try:
            from pptx import Presentation
        except ImportError:
            raise PptParseError(
                "python-pptx is required for PowerPoint support. "
                "Install it with: pip install python-pptx"
            )

        try:
            prs = Presentation(file_path)
        except Exception as exc:
            raise PptParseError(f"Failed to read PowerPoint file: {exc}") from exc

        pages: list[PdfPage] = []

        for slide_idx, slide in enumerate(prs.slides, start=1):
            parts: list[str] = []

            # Extract slide title
            if slide.has_notes_slide and slide.placeholders:
                pass  # handled below

            # Extract text from shapes
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        text = paragraph.text.strip()
                        if text:
                            parts.append(text)

                # Extract tables
                if shape.has_table:
                    table = shape.table
                    table_lines = []
                    header = []
                    for cell in table.rows[0].cells:
                        header.append(cell.text.strip())
                    table_lines.append(" | ".join(header))
                    table_lines.append(" | ".join(["---"] * len(header)))

                    for row in table.rows[1:]:
                        cells = [cell.text.strip() for cell in row.cells]
                        table_lines.append(" | ".join(cells))

                    if table_lines:
                        parts.append("\n".join(table_lines))

            # Extract speaker notes
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    parts.append(f"Speaker Notes: {notes_text}")

            if parts:
                page_text = "\n\n".join(parts)
            else:
                page_text = f"Slide {slide_idx} (no text content)"

            pages.append(PdfPage(
                page_number=slide_idx,
                extracted_text=page_text,
            ))

        return ParsedPdf(pages=pages, total_pages=len(pages))
