from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List

from langparse.chunkers.blocks import CODE, HEADING, PAGE_MARKER, TABLE, Block, scan_blocks
from langparse.core.chunker import BaseChunker
from langparse.types import Chunk, Document

SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s+")
JOIN = "\n\n"


@dataclass
class _Section:
    header: str | None = None
    header_level: int = 0
    header_path: str = ""
    blocks: List[Block] = field(default_factory=list)
    page_numbers: set = field(default_factory=set)


@dataclass
class _Unit:
    """One packable piece of content. Oversized units get a chunk to themselves."""

    text: str
    oversized: bool = False


class SemanticChunker(BaseChunker):
    """
    Chunks text on Markdown structure, keeping chunks within a size budget.

    Sections come from heading structure; within a section, blocks are packed
    greedily up to `max_chunk_size`. Size is measured by `length_function`, so
    callers embedding against a token budget can pass a tokenizer's encoder
    instead of the default character count.
    """

    def __init__(
        self,
        max_chunk_size: int = 1000,
        overlap: int = 0,
        length_function: Callable[[str], int] = len,
    ):
        if overlap >= max_chunk_size:
            raise ValueError("overlap must be smaller than max_chunk_size")
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.length_function = length_function

    def chunk(self, document: Document, **kwargs) -> List[Chunk]:
        sections = self._sections(scan_blocks(document.content))

        chunks: List[Chunk] = []
        for section in sections:
            units = self._units_for(section.blocks)
            for text, oversized in self._pack(units):
                metadata = document.metadata.copy()
                metadata.update(
                    {
                        "header": section.header,
                        "header_level": section.header_level,
                        "header_path": section.header_path,
                        "page_numbers": sorted(section.page_numbers) or [1],
                        "chunk_index": len(chunks),
                    }
                )
                if oversized:
                    metadata["oversized"] = True
                chunks.append(Chunk(content=text, metadata=metadata))

        return chunks

    # -- sectioning ---------------------------------------------------------

    def _sections(self, blocks: List[Block]) -> List[_Section]:
        sections: List[_Section] = []
        header_stack: List[tuple[int, str]] = []
        current_page = 1
        current = _Section(page_numbers={current_page})

        for block in blocks:
            if block.kind == PAGE_MARKER:
                current_page = block.page_number
                current.page_numbers.add(current_page)
                continue

            if block.kind == HEADING:
                if current.blocks:
                    sections.append(current)
                while header_stack and header_stack[-1][0] >= block.level:
                    header_stack.pop()
                header_stack.append((block.level, block.title))
                current = _Section(
                    header=block.title,
                    header_level=block.level,
                    header_path=" > ".join(title for _, title in header_stack),
                    blocks=[block],
                    page_numbers={current_page},
                )
                continue

            current.blocks.append(block)

        if current.blocks:
            sections.append(current)
        return sections

    # -- unit expansion -----------------------------------------------------

    def _units_for(self, blocks: List[Block]) -> List[_Unit]:
        units: List[_Unit] = []
        for block in blocks:
            if self._fits(block.text):
                units.append(_Unit(block.text))
            elif block.kind == TABLE:
                units.extend(_Unit(part) for part in self._split_table(block))
            elif block.kind == CODE:
                # Splitting a fenced block would leave unterminated fences, so it
                # travels whole and is flagged for the caller to notice.
                units.append(_Unit(block.text, oversized=True))
            else:
                units.extend(_Unit(part) for part in self._split_prose(block.text))
        return units

    def _split_table(self, block: Block) -> List[str]:
        """Split by row, repeating the header so each part reads on its own."""
        if not block.rows:
            return [block.text]

        header, *data_rows = block.rows
        header_markdown = [_row_markdown(header), _separator_markdown(len(header))]
        header_size = self.length_function("\n".join(header_markdown))

        parts: List[str] = []
        pending: List[str] = []
        pending_size = header_size

        for row in data_rows:
            rendered = _row_markdown(row)
            row_size = self.length_function(rendered) + 1
            if pending and pending_size + row_size > self.max_chunk_size:
                parts.append("\n".join(header_markdown + pending))
                pending, pending_size = [], header_size
            pending.append(rendered)
            pending_size += row_size

        if pending:
            parts.append("\n".join(header_markdown + pending))
        return parts or [block.text]

    def _split_prose(self, text: str) -> List[str]:
        parts: List[str] = []
        pending = ""
        for sentence in SENTENCE_END_RE.split(text):
            if not sentence:
                continue
            candidate = f"{pending} {sentence}".strip() if pending else sentence
            if pending and not self._fits(candidate):
                parts.append(pending)
                pending = sentence
            else:
                pending = candidate

            while not self._fits(pending):
                head, pending = self._cut_to_fit(pending)
                parts.append(head)

        if pending:
            parts.append(pending)
        return parts

    def _cut_to_fit(self, text: str) -> tuple[str, str]:
        """Hard-split a run that no sentence boundary can bring under budget."""
        low, high, best = 1, len(text), 1
        while low <= high:
            middle = (low + high) // 2
            if self.length_function(text[:middle]) <= self.max_chunk_size:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return text[:best], text[best:]

    # -- packing ------------------------------------------------------------

    def _pack(self, units: List[_Unit]) -> List[tuple[str, bool]]:
        packed: List[tuple[str, bool]] = []
        pending: List[str] = []

        def flush():
            if pending:
                packed.append((JOIN.join(pending), False))
                pending.clear()

        for unit in units:
            if unit.oversized:
                flush()
                packed.append((unit.text, True))
                continue

            if pending and not self._fits(JOIN.join(pending + [unit.text])):
                flush()
            pending.append(unit.text)

        flush()
        return self._apply_overlap(packed)

    def _apply_overlap(self, packed: List[tuple[str, bool]]) -> List[tuple[str, bool]]:
        if self.overlap <= 0 or len(packed) < 2:
            return packed

        result = [packed[0]]
        for index in range(1, len(packed)):
            text, oversized = packed[index]
            tail = self._tail(packed[index - 1][0])
            result.append((f"{tail}{JOIN}{text}" if tail else text, oversized))
        return result

    def _tail(self, text: str) -> str:
        """Longest whitespace-aligned suffix that fits the overlap budget."""
        words = text.split()
        tail = ""
        for count in range(1, len(words) + 1):
            candidate = " ".join(words[-count:])
            if self.length_function(candidate) > self.overlap:
                break
            tail = candidate
        return tail

    def _fits(self, text: str) -> bool:
        return self.length_function(text) <= self.max_chunk_size


def _row_markdown(row: List[str]) -> str:
    return f"| {' | '.join(row)} |"


def _separator_markdown(width: int) -> str:
    return f"| {' | '.join(['---'] * width)} |"
