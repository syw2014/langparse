"""
Scan Markdown into typed blocks.

Chunking used to run a heading regex over the whole document, which cannot tell
a real heading from a `#` comment inside a fenced code block -- recognising a
fence requires tracking state across lines. Scanning into typed blocks fixes
that structurally, and the same block types are what let the packer treat
tables and code differently when they overflow a chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
PAGE_MARKER_RE = re.compile(r"^\s*<!--\s*page_number:\s*(\d+)\s*-->\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")

HEADING = "heading"
TABLE = "table"
CODE = "code"
PARAGRAPH = "paragraph"
PAGE_MARKER = "page_marker"


@dataclass
class Block:
    kind: str
    text: str
    #: heading only
    level: int = 0
    title: str = ""
    #: table only
    rows: list[list[str]] = field(default_factory=list)
    has_header: bool = False
    #: page_marker only
    page_number: int = 0


def scan_blocks(markdown: str) -> list[Block]:
    """Split Markdown into an ordered list of typed blocks."""
    if not markdown:
        return []

    lines = markdown.splitlines()
    blocks: list[Block] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if not line.strip():
            index += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            index = _consume_fence(lines, index, fence.group(2), blocks)
            continue

        page_marker = PAGE_MARKER_RE.match(line)
        if page_marker:
            blocks.append(
                Block(kind=PAGE_MARKER, text=line, page_number=int(page_marker.group(1)))
            )
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            blocks.append(
                Block(
                    kind=HEADING,
                    text=line,
                    level=len(heading.group(1)),
                    title=heading.group(2),
                )
            )
            index += 1
            continue

        if _starts_table(lines, index):
            index = _consume_table(lines, index, blocks)
            continue

        index = _consume_paragraph(lines, index, blocks)

    return blocks


def _consume_fence(lines: list[str], index: int, marker: str, blocks: list[Block]) -> int:
    """Consume a fenced block. An unclosed fence runs to end of input."""
    fence_char = marker[0]
    collected = [lines[index]]
    index += 1

    while index < len(lines):
        collected.append(lines[index])
        closing = FENCE_RE.match(lines[index])
        index += 1
        if closing and closing.group(2)[0] == fence_char and len(closing.group(2)) >= len(marker):
            break

    blocks.append(Block(kind=CODE, text="\n".join(collected)))
    return index


def _starts_table(lines: list[str], index: int) -> bool:
    """A table needs a pipe row followed by a separator row; pipes alone are prose."""
    if not lines[index].lstrip().startswith("|"):
        return False
    return index + 1 < len(lines) and bool(TABLE_SEPARATOR_RE.match(lines[index + 1]))


def _consume_table(lines: list[str], index: int, blocks: list[Block]) -> int:
    collected: list[str] = []
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        collected.append(lines[index])
        index += 1

    rows = [
        _split_table_row(line)
        for line in collected
        if not TABLE_SEPARATOR_RE.match(line)
    ]
    blocks.append(
        Block(kind=TABLE, text="\n".join(collected), rows=rows, has_header=bool(rows))
    )
    return index


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _consume_paragraph(lines: list[str], index: int, blocks: list[Block]) -> int:
    collected: list[str] = []
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        if (
            FENCE_RE.match(line)
            or HEADING_RE.match(line)
            or PAGE_MARKER_RE.match(line)
            or _starts_table(lines, index)
        ):
            break
        collected.append(line)
        index += 1

    if collected:
        blocks.append(Block(kind=PARAGRAPH, text="\n".join(collected)))
    return index
