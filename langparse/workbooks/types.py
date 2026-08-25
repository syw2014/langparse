from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from langparse.types import ParsedStructure, StructuredData


def stable_id(prefix: str, *parts: str) -> str:
    """Build a compact deterministic identifier from source identity parts."""

    payload = "\x1f".join((prefix, *parts)).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class SourceRef:
    sheet_name: str
    range: str

    @property
    def key(self) -> str:
        return f"{self.sheet_name}!{self.range}"


@dataclass
class CellSnapshot:
    coordinate: str
    raw_value: Any = None
    display_value: str = ""
    formula: str | None = None
    cached_value: Any = None
    data_type: str = ""
    number_format: str = "General"
    style_id: str = ""
    merge_anchor: str | None = None
    rowspan: int = 1
    colspan: int = 1
    hyperlink: str | None = None
    comment: str | None = None
    hidden: bool = False


@dataclass
class SheetSnapshot:
    name: str
    index: int
    visibility: str = "visible"
    used_range: str | None = None
    print_area: list[str] = field(default_factory=list)
    row_heights: dict[int, float] = field(default_factory=dict)
    column_widths: dict[str, float] = field(default_factory=dict)
    hidden_rows: list[int] = field(default_factory=list)
    hidden_columns: list[str] = field(default_factory=list)
    merged_ranges: list[str] = field(default_factory=list)
    cells: dict[str, CellSnapshot] = field(default_factory=dict)
    objects: list[StructuredData] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class WorkbookSnapshot:
    source: str
    filename: str
    sheets: list[SheetSnapshot] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class WorkbookBlock:
    block_id: str
    kind: str
    source_refs: list[SourceRef] = field(default_factory=list)
    cell_refs: list[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: StructuredData = field(default_factory=dict)
    diagnostics: list[StructuredData] = field(default_factory=list)


@dataclass
class SheetIR:
    sheet_id: str
    name: str
    index: int
    blocks: list[WorkbookBlock] = field(default_factory=list)
    visibility: str = "visible"
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class WorkbookIR(ParsedStructure):
    workbook_id: str
    source: str
    sheets: list[SheetIR] = field(default_factory=list)
    filename: str = ""
    metadata: StructuredData = field(default_factory=dict)

