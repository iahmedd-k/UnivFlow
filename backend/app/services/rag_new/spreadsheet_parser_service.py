from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

from app.services.pdf_parser_service import ParsedPdf, PdfPage

logger = logging.getLogger(__name__)


class SpreadsheetParseError(Exception):
    """Raised when a CSV/Excel file cannot be read or parsed."""


@dataclass
class SpreadsheetParserService:
    """Parse CSV and Excel files into ParsedPdf format.

    CSV files are parsed row-by-row, with each row rendered as pipe-delimited
    text (compatible with the existing table chunking logic). Column headers
    are repeated in each chunk for self-containment.

    Excel files (.xlsx, .xls) are parsed using openpyxl, with each sheet
    becoming a separate page. Tables are rendered as pipe-delimited text.
    """

    def parse(self, file_path: str, mime_type: str = "") -> ParsedPdf:
        """Parse a CSV or Excel file and return ParsedPdf."""
        lower_path = file_path.lower()

        if lower_path.endswith(".csv") or "csv" in mime_type:
            return self._parse_csv(file_path)
        elif lower_path.endswith((".xlsx", ".xls")) or "excel" in mime_type or "spreadsheet" in mime_type:
            return self._parse_excel(file_path)
        else:
            raise SpreadsheetParseError(f"Unsupported spreadsheet format: {file_path}")

    def _parse_csv(self, file_path: str) -> ParsedPdf:
        """Parse a CSV file into ParsedPdf with pipe-delimited table rows."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="latin-1") as f:
                    content = f.read()
            except Exception as exc:
                raise SpreadsheetParseError(f"Failed to read CSV file: {exc}") from exc
        except Exception as exc:
            raise SpreadsheetParseError(f"Failed to read CSV file: {exc}") from exc

        try:
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
        except Exception as exc:
            raise SpreadsheetParseError(f"Failed to parse CSV: {exc}") from exc

        if not rows:
            return ParsedPdf(pages=[], total_pages=0)

        # Use first row as header
        header = rows[0]
        data_rows = rows[1:]

        # Build pipe-delimited table text
        lines = []
        header_line = " | ".join(str(cell).strip() for cell in header)
        lines.append(header_line)
        lines.append(" | ".join(["---"] * len(header)))

        for row in data_rows:
            # Pad row to match header length
            padded = row + [""] * (len(header) - len(row)) if len(row) < len(header) else row[:len(header)]
            line = " | ".join(str(cell).strip() for cell in padded)
            lines.append(line)

        table_text = "\n".join(lines)

        # Create a single page with the table
        page = PdfPage(
            page_number=1,
            extracted_text=f"Table: CSV Data\n\n{table_text}",
        )

        return ParsedPdf(pages=[page], total_pages=1)

    def _parse_excel(self, file_path: str) -> ParsedPdf:
        """Parse an Excel file into ParsedPdf with one page per sheet."""
        try:
            import openpyxl
        except ImportError:
            raise SpreadsheetParseError(
                "openpyxl is required for Excel file support. "
                "Install it with: pip install openpyxl"
            )

        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        except Exception as exc:
            raise SpreadsheetParseError(f"Failed to read Excel file: {exc}") from exc

        pages: list[PdfPage] = []

        for sheet_idx, sheet_name in enumerate(wb.sheetnames, start=1):
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                # Filter out completely empty rows
                if any(cell is not None for cell in row):
                    rows.append(row)

            if not rows:
                continue

            # Build pipe-delimited table
            lines = []
            header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
            header_line = " | ".join(header)
            lines.append(header_line)
            lines.append(" | ".join(["---"] * len(header)))

            for row in rows[1:]:
                cells = [str(cell).strip() if cell is not None else "" for cell in row]
                # Pad to match header length
                if len(cells) < len(header):
                    cells.extend([""] * (len(header) - len(cells)))
                elif len(cells) > len(header):
                    cells = cells[:len(header)]
                line = " | ".join(cells)
                lines.append(line)

            table_text = "\n".join(lines)
            page_text = f"Sheet: {sheet_name}\n\n{table_text}"

            pages.append(PdfPage(
                page_number=sheet_idx,
                extracted_text=page_text,
            ))

        wb.close()

        return ParsedPdf(pages=pages, total_pages=len(pages))
