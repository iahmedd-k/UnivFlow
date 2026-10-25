import logging
import re
from uuid import uuid4

from app.core.config import settings
from app.schemas.chunk import DocumentChunk
from app.services.pdf_parser_service import ParsedPdf

logger = logging.getLogger(__name__)

# Minimum token count for a chunk. Anything shorter is merged with a neighbor.
_MIN_CHUNK_TOKENS = 20

# Lazy-loaded tokenizer singleton for token-aware chunking
_tokenizer = None
_tokenizer_loaded = False


def _get_tokenizer():
    """Return a tokenizer for token-count-based chunking.

    Uses the same model family as the embedding model. Falls back to
    whitespace splitting if transformers is not available.
    """
    global _tokenizer, _tokenizer_loaded
    if _tokenizer_loaded:
        return _tokenizer
    _tokenizer_loaded = True
    try:
        from transformers import AutoTokenizer

        model_name = "Snowflake/snowflake-arctic-embed-m"
        _tokenizer = AutoTokenizer.from_pretrained(model_name)
        logger.info("Loaded tokenizer %s for chunk sizing", model_name)
    except Exception:
        logger.debug(
            "Could not load tokenizer; falling back to whitespace splitting"
        )
        _tokenizer = None
    return _tokenizer


def _token_count(text: str) -> int:
    """Count tokens in text using the embedding model's tokenizer."""
    tok = _get_tokenizer()
    if tok is not None:
        return len(tok.encode(text, add_special_tokens=False))
    return len(text.split())


class ContentType:
    TEXT = "text"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"


# ---------------------------------------------------------------------------
# Section headers — resume/document structure keywords
# ---------------------------------------------------------------------------
_RESUME_SECTION_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"(?:professional\s+)?(?:summary|objective|profile)"
    r"|(?:work\s+)?(?:experience|employment|history)"
    r"|education(?:al\s+background)?"
    r"|skills?(?:\s*\([^)]*\))?"
    r"|technical\s+skills?"
    r"|projects?(?:\s*\([^)]*\))?"
    r"|certifications?"
    r"|awards?"
    r"|honors?"
    r"|activities?"
    r"|volunteer(?:ing)?(?:\s+experience)?"
    r"|references?"
    r"|languages?"
    r"|interests?"
    r"|publications?"
    r"|patents?"
    r"|portfolio"
    r"|contact(?:\s+info(?:rmation)?)?"
    r"|address"
    r"|phone"
    r"|email"
    r"|linkedin"
    r"|github"
    r"|portfolio"
    r"|DECLARATION"
    r"|PERSONAL\s+DETAILS?"
    r"|DATE\s+OF\s+BIRTH"
    r"|MARITAL\s+STATUS"
    r"|NATIONALITY"
    r"|PASSPORT"
    r"|VISA"
    r"|DECLARATION"
    r")\s*$",
    re.IGNORECASE,
)

# Generic structural headings (section/chapter/appendix prefix patterns)
_STRUCTURAL_HEADING_RE = re.compile(
    r"^\s*"
    r"(?:section|chapter|appendix|part|volume|module|unit)"
    r"\s+"
    r"(?:\d+(?:\.\d+)*[.:]?\s+)?"
    r".+",
    re.IGNORECASE,
)

# Numbered section headings: "1. Introduction", "2.1 Background", etc.
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*\d+(?:\.\d+)*[.:]?\s+"
    r"[A-Z][A-Za-z0-9'&. -]+"
    r"\s*$"
)

# Headings look like short, non-punctuated section titles.
_HEADING_RE = re.compile(
    r"^\s*"
    r"(?:[A-Z][A-Za-z0-9'&.-]*(?:\s+[A-Z][A-Za-z0-9'&.-]*)*)"
    r"\s*$"
)

# A bullet/numbered list marker. Covers "-", "*", "•", "1.", "a)", "(i)" etc.
_LIST_RE = re.compile(
    r"^\s*(?:[-*•◦▪]|\d{1,3}[.)]|[a-z][.)]|[ivxIVX]+[.)]|\([a-z0-9]+\))\s+"
)

# A table row has at least two columns separated by a "|" or multiple spaces.
_TABLE_ROW_RE = re.compile(r"^\s*(?:[^|]*\|[^|]*){1,}\s*$")
_WIDE_SPACE_TABLE_RE = re.compile(r"^\s*\S+(?:  +\S+)+\s*$")


class ChunkingService:

    def chunk_document(self, parsed: ParsedPdf, document_id: int) -> list[DocumentChunk]:
        """Convert a parsed PDF into structure-aware in-memory chunks.

        Chunks are transient objects; nothing is written to any persistence layer.
        """
        chunks: list[DocumentChunk] = []
        counter = 0

        for page in parsed.pages:
            blocks = self._split_into_blocks(page.extracted_text)
            for block in blocks:
                block_chunks = self._chunk_block(
                    block,
                    document_id=document_id,
                    page_number=page.page_number,
                    seq_start=counter,
                )
                for chunk in block_chunks:
                    counter += 1
                    chunks.append(chunk)

        # Post-process: merge undersized chunks with neighbors
        chunks = self._merge_undersized_chunks(chunks, document_id)

        # Log quality metrics
        self._log_chunk_quality(chunks, document_id)

        return chunks

    # ------------------------------------------------------------------ #
    # Post-processing: merge undersized chunks
    # ------------------------------------------------------------------ #

    def _merge_undersized_chunks(
        self, chunks: list[DocumentChunk], document_id: int
    ) -> list[DocumentChunk]:
        """Merge chunks that are too small with their neighbors.

        A chunk is undersized if it has fewer than _MIN_CHUNK_TOKENS tokens.
        It tries to merge into the previous chunk of the same content_type
        and same page_number.  Chunks that cannot merge (different type,
        different page, or would exceed chunk_size tokens) are kept as-is.
        """
        if not chunks:
            return []

        merged: list[DocumentChunk] = []
        for chunk in chunks:
            if _token_count(chunk.content) < _MIN_CHUNK_TOKENS:
                # Try merging into the previous chunk of the same type AND page
                if (
                    merged
                    and merged[-1].content_type == chunk.content_type
                    and merged[-1].page_number == chunk.page_number
                ):
                    prev = merged[-1]
                    combined_content = prev.content + " " + chunk.content
                    if _token_count(combined_content) <= settings.chunk_size:
                        merged[-1] = DocumentChunk(
                            chunk_id=prev.chunk_id,
                            document_id=prev.document_id,
                            page_number=prev.page_number,
                            page_numbers=prev.page_numbers,
                            content=combined_content,
                            content_type=prev.content_type,
                            metadata=prev.metadata,
                        )
                        continue
                # Cannot merge — keep as-is
                merged.append(chunk)
                continue
            merged.append(chunk)

        # Handle the first chunk being undersized — merge forward if same type/page
        if (
            len(merged) > 1
            and _token_count(merged[0].content) < _MIN_CHUNK_TOKENS
            and merged[0].content_type == merged[1].content_type
            and merged[0].page_number == merged[1].page_number
        ):
            first = merged[0]
            second = merged[1]
            combined = first.content + " " + second.content
            if _token_count(combined) <= settings.chunk_size:
                merged[1] = DocumentChunk(
                    chunk_id=second.chunk_id,
                    document_id=second.document_id,
                    page_number=second.page_number,
                    page_numbers=second.page_numbers,
                    content=combined,
                    content_type=second.content_type,
                    metadata=second.metadata,
                )
                merged = merged[1:]

        return merged

    # ------------------------------------------------------------------ #
    # Quality logging
    # ------------------------------------------------------------------ #

    @staticmethod
    def _log_chunk_quality(chunks: list[DocumentChunk], document_id: int) -> None:
        """Log chunk count and size distribution for ingestion validation."""
        if not chunks:
            logger.warning("Document %d produced 0 chunks", document_id)
            return

        lengths = [len(c.content.split()) for c in chunks]
        undersized = sum(1 for l in lengths if l < _MIN_CHUNK_TOKENS)

        logger.info(
            "Document %d: %d chunks, token counts: min=%d max=%d avg=%.0f, "
            "undersized (<%d tokens): %d",
            document_id,
            len(chunks),
            min(lengths),
            max(lengths),
            sum(lengths) / len(lengths),
            _MIN_CHUNK_TOKENS,
            undersized,
        )

        if undersized:
            logger.warning(
                "Document %d: %d chunks below minimum token threshold (%d). "
                "These should have been merged.",
                document_id,
                undersized,
                _MIN_CHUNK_TOKENS,
            )

    # ------------------------------------------------------------------ #
    # Structure detection
    # ------------------------------------------------------------------ #

    def _split_into_blocks(self, text: str) -> list[dict]:
        """Split raw page text into structural blocks (dicts).

        Each block is one of:
            {"type": "text",     "lines": [...]}
            {"type": "heading",  "text": "..."}
            {"type": "list",     "items": [...]}
            {"type": "table",    "rows": [[...], ...], "header": [...]}
        """
        raw_lines = [ln for ln in text.splitlines() if ln.strip()]
        if not raw_lines:
            return []

        # Pre-pass: merge consecutive short lines into paragraphs
        raw_lines = self._merge_short_lines(raw_lines)

        blocks: list[dict] = []
        i = 0
        n = len(raw_lines)

        while i < n:
            line = raw_lines[i]

            if self._is_heading(line):
                blocks.append({"type": ContentType.HEADING, "text": line.strip()})
                i += 1
                continue

            if self._is_table_row(line) and self._starts_table(raw_lines, i):
                header, body, next_i = self._collect_table(raw_lines, i)
                blocks.append(
                    {"type": ContentType.TABLE, "header": header, "rows": body}
                )
                i = next_i
                continue

            if _LIST_RE.match(line):
                items, next_i = self._collect_list(raw_lines, i)
                blocks.append({"type": ContentType.LIST, "items": items})
                i = next_i
                continue

            # Normal text: gather a paragraph (consecutive non-structural lines).
            para_lines = [line]
            j = i + 1
            while (
                j < n
                and not self._is_heading(raw_lines[j])
                and not _LIST_RE.match(raw_lines[j])
                and not (
                    self._is_table_row(raw_lines[j])
                    and self._starts_table(raw_lines, j)
                )
            ):
                para_lines.append(raw_lines[j])
                j += 1
            blocks.append({"type": ContentType.TEXT, "lines": para_lines})
            i = j

        return blocks

    @classmethod
    def _merge_short_lines(cls, lines: list[str]) -> list[str]:
        """Merge consecutive short lines (<40 chars each) into single lines.

        This handles the common case where PDF extraction breaks a paragraph
        into many short fragments (one word per line). Lines that are already
        substantial (>=40 chars) are kept as-is and act as merge boundaries.
        Structural elements (table rows) are never merged into text paragraphs.
        """
        if not lines:
            return []

        SHORT_THRESHOLD = 40
        merged: list[str] = []
        buffer: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if buffer:
                    merged.append(" ".join(buffer))
                    buffer = []
                continue

            # Do not merge table rows into text paragraphs
            if cls._is_table_row(stripped):
                if buffer:
                    merged.append(" ".join(buffer))
                    buffer = []
                merged.append(stripped)
                continue

            if len(stripped) < SHORT_THRESHOLD and not stripped[-1] in ".!?":
                buffer.append(stripped)
            else:
                if buffer:
                    merged.append(" ".join(buffer))
                    buffer = []
                merged.append(stripped)

        if buffer:
            merged.append(" ".join(buffer))

        return merged

    @staticmethod
    def _is_heading(line: str) -> bool:
        """Determine if a line is a section heading.

        Uses a conservative approach:
        1. Resume section keywords (EXPERIENCE, EDUCATION, SKILLS, etc.)
        2. Structural patterns (Section 1, Chapter 2, Appendix A)
        3. Numbered headings (1. Introduction, 2.1 Background)
        4. Short ALL-CAPS titles (but not single generic words)
        """
        stripped = line.strip()
        if not stripped:
            return False

        # Length guard
        if len(stripped) > 80:
            return False

        # Exclude list items and table rows
        if _LIST_RE.match(stripped):
            return False
        if _TABLE_ROW_RE.match(stripped):
            return False

        # Exclude lines ending with sentence punctuation
        if stripped[-1] in ".,;:!?":
            return False

        # 1. Resume section headers (most important for resumes)
        if _RESUME_SECTION_RE.match(stripped):
            return True

        # 2. Structural patterns: "Section 1:", "Chapter 2", "Appendix A"
        if _STRUCTURAL_HEADING_RE.match(stripped):
            return True

        # 3. Numbered headings: "1. Introduction", "2.1 Background"
        if _NUMBERED_HEADING_RE.match(stripped):
            return True

        # 4. Short titles that are ALL CAPS or Title Case, multi-word
        words = stripped.split()
        if len(words) >= 2:
            # Check if it looks like a title (ALL CAPS or Title Case)
            all_caps = stripped.isupper()
            title_case = all(
                w[0].isupper() for w in words if len(w) > 1
            )
            if all_caps or title_case:
                # Additional check: not too many words (titles are short)
                if len(words) <= 6:
                    return True

        return False

    @staticmethod
    def _is_table_row(line: str) -> bool:
        return bool(_TABLE_ROW_RE.match(line)) or bool(
            _WIDE_SPACE_TABLE_RE.match(line)
        )

    @staticmethod
    def _starts_table(lines: list[str], i: int) -> bool:
        # A table needs a header (or at least) two consecutive table-like rows.
        return i + 1 < len(lines) and (
            _TABLE_ROW_RE.match(lines[i]) and _TABLE_ROW_RE.match(lines[i + 1])
        ) or (
            i + 1 < len(lines)
            and _WIDE_SPACE_TABLE_RE.match(lines[i])
            and _WIDE_SPACE_TABLE_RE.match(lines[i + 1])
        )

    @staticmethod
    def _collect_table(lines: list[str], i: int) -> tuple[list[str], list[list[str]], int]:
        rows: list[list[str]] = []
        j = i
        while j < len(lines):
            line = lines[j]
            if _TABLE_ROW_RE.match(line) or _WIDE_SPACE_TABLE_RE.match(line):
                rows.append(_split_row(line))
                j += 1
            else:
                break
        if not rows:
            rows = [[lines[i]]]
            j = i + 1
        header = rows[0]
        body = rows[1:]
        return header, body, j

    @staticmethod
    def _collect_list(lines: list[str], i: int) -> tuple[list[str], int]:
        items: list[str] = []
        j = i
        while j < len(lines):
            line = lines[j]
            if _LIST_RE.match(line):
                items.append(line.strip())
                j += 1
            else:
                break
        return items, j

    # ------------------------------------------------------------------ #
    # Chunk construction
    # ------------------------------------------------------------------ #

    def _chunk_block(
        self,
        block: dict,
        document_id: int,
        page_number: int,
        seq_start: int,
    ) -> list[DocumentChunk]:
        if block["type"] == ContentType.TABLE:
            return self._chunk_table(
                block,
                document_id=document_id,
                page_number=page_number,
                seq_start=seq_start,
            )
        if block["type"] == ContentType.LIST:
            return self._chunk_list(
                block,
                document_id=document_id,
                page_number=page_number,
                seq_start=seq_start,
            )
        if block["type"] == ContentType.HEADING:
            return self._chunk_heading(
                block,
                document_id=document_id,
                page_number=page_number,
                seq_start=seq_start,
            )
        return self._chunk_text(
            block,
            document_id=document_id,
            page_number=page_number,
            seq_start=seq_start,
        )

    def _make_chunk(
        self,
        document_id: int,
        page_number: int,
        content: str,
        content_type: str,
        seq: int,
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=f"doc-{document_id}-{seq + 1}",
            document_id=document_id,
            page_number=page_number,
            page_numbers=[page_number],
            content=content,
            content_type=content_type,
            metadata={"source": "pdf", "page": page_number},
        )

    # -- headings ----------------------------------------------------- #
    def _chunk_heading(
        self,
        block: dict,
        document_id: int,
        page_number: int,
        seq_start: int,
    ) -> list[DocumentChunk]:
        text = block["text"]
        if _token_count(text) <= settings.chunk_size:
            return [
                self._make_chunk(
                    document_id,
                    page_number,
                    text,
                    ContentType.HEADING,
                    seq_start,
                )
            ]
        # Extremely rare: a heading larger than the chunk size.
        return self._split_text(
            text,
            document_id,
            page_number,
            ContentType.HEADING,
            seq_start,
        )

    # -- normal text -------------------------------------------------- #
    def _chunk_text(
        self,
        block: dict,
        document_id: int,
        page_number: int,
        seq_start: int,
    ) -> list[DocumentChunk]:
        paragraph = " ".join(ln.strip() for ln in block["lines"]).strip()
        if not paragraph:
            return []
        if _token_count(paragraph) <= settings.chunk_size:
            return [
                self._make_chunk(
                    document_id,
                    page_number,
                    paragraph,
                    ContentType.TEXT,
                    seq_start,
                )
            ]
        return self._split_text(
            paragraph,
            document_id,
            page_number,
            ContentType.TEXT,
            seq_start,
        )

    # -- lists -------------------------------------------------------- #
    def _chunk_list(
        self,
        block: dict,
        document_id: int,
        page_number: int,
        seq_start: int,
    ) -> list[DocumentChunk]:
        items = block["items"]
        groups: list[list[str]] = []
        current: list[str] = []

        for item in items:
            if _token_count(item) > settings.chunk_size:
                if current:
                    groups.append(current)
                    current = []
                groups.append([item])
                continue
            trial = " ".join(current + [item])
            if current and _token_count(trial) > settings.chunk_size:
                groups.append(current)
                current = [item]
            else:
                current.append(item)
        if current:
            groups.append(current)

        chunks: list[DocumentChunk] = []
        seq = seq_start
        for group in groups:
            content = " ".join(group)
            if _token_count(content) <= settings.chunk_size:
                chunks.append(
                    self._make_chunk(
                        document_id,
                        page_number,
                        content,
                        ContentType.LIST,
                        seq,
                    )
                )
                seq += 1
            else:
                sub_chunks = self._split_text(
                    content,
                    document_id,
                    page_number,
                    ContentType.LIST,
                    seq,
                )
                chunks.extend(sub_chunks)
                seq += len(sub_chunks)
        return chunks

    # -- tables ------------------------------------------------------- #
    def _chunk_table(
        self,
        block: dict,
        document_id: int,
        page_number: int,
        seq_start: int,
    ) -> list[DocumentChunk]:
        header = block["header"]
        body = block["rows"]
        header_text = _render_table_header(header)

        if len(body) <= 1:
            content = _render_table(header, body)
            return [
                self._make_chunk(
                    document_id,
                    page_number,
                    content,
                    ContentType.TABLE,
                    seq_start,
                )
            ]

        # Large table: split by rows, repeating the header in every chunk.
        chunks: list[DocumentChunk] = []
        seq = seq_start
        group: list[list[str]] = []
        current_size = 0

        for row in body:
            row_size = _token_count(_render_row(row))
            if group and current_size + row_size > settings.chunk_size:
                content = _render_table_with_header(header_text, group)
                chunks.append(
                    self._make_chunk(
                        document_id,
                        page_number,
                        content,
                        ContentType.TABLE,
                        seq,
                    )
                )
                seq += 1
                group = [row]
                current_size = row_size
            else:
                group.append(row)
                current_size += row_size

        if group:
            content = _render_table_with_header(header_text, group)
            chunks.append(
                self._make_chunk(
                    document_id,
                    page_number,
                    content,
                    ContentType.TABLE,
                    seq,
                )
            )

        return chunks

    # -- generic splitting -------------------------------------------- #
    def _split_text(
        self,
        text: str,
        document_id: int,
        page_number: int,
        content_type: str,
        seq_start: int,
    ) -> list[DocumentChunk]:
        """Split text into chunks by token count with overlap.

        Uses the embedding model's tokenizer for accurate token counting
        to ensure no chunk exceeds the model's context window.
        """
        tok = _get_tokenizer()
        if tok is None:
            # Fallback: character-based splitting
            return self._split_text_by_chars(
                text, document_id, page_number, content_type, seq_start
            )

        tokens = tok.encode(text, add_special_tokens=False)
        size = settings.chunk_size
        overlap = settings.chunk_overlap
        step = max(1, size - overlap)
        chunks: list[DocumentChunk] = []
        seq = seq_start
        start = 0
        length = len(tokens)

        while start < length:
            end = min(start + size, length)
            token_slice = tokens[start:end]
            piece = tok.decode(token_slice, skip_special_tokens=True).strip()
            if piece:
                chunks.append(
                    self._make_chunk(
                        document_id,
                        page_number,
                        piece,
                        content_type,
                        seq,
                    )
                )
                seq += 1
            if end >= length:
                break
            start += step

        return chunks

    def _split_text_by_chars(
        self,
        text: str,
        document_id: int,
        page_number: int,
        content_type: str,
        seq_start: int,
    ) -> list[DocumentChunk]:
        """Fallback: character-based splitting when tokenizer unavailable."""
        # Approximate: ~4 chars per token for English
        size = settings.chunk_size * 4
        overlap = min(settings.chunk_overlap * 4, size // 2)
        step = max(1, size - overlap)
        chunks: list[DocumentChunk] = []
        seq = seq_start
        start = 0
        length = len(text)

        while start < length:
            end = min(start + size, length)
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    self._make_chunk(
                        document_id,
                        page_number,
                        piece,
                        content_type,
                        seq,
                    )
                )
                seq += 1
            if end >= length:
                break
            start += step

        return chunks


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if "|" in stripped:
        inner = stripped
        if inner.startswith("|"):
            inner = inner[1:]
        if inner.endswith("|"):
            inner = inner[:-1]
        cells = [c.strip() for c in inner.split("|")]
        if cells:
            return cells
    # Fall back to splitting on wide whitespace runs.
    parts = re.split(r"\s{2,}", stripped)
    return [p.strip() for p in parts if p.strip()]


def _render_row(row: list[str]) -> str:
    return " | ".join(cell for cell in row)


def _render_table(header: list[str], body: list[list[str]]) -> str:
    lines = [_render_row(header)]
    lines.extend(_render_row(row) for row in body)
    return "\n".join(lines)


def _render_table_header(header: list[str]) -> str:
    return _render_row(header)


def _render_table_with_header(header_text: str, rows: list[list[str]]) -> str:
    lines = [header_text]
    lines.extend(_render_row(row) for row in rows)
    return "\n".join(lines)
