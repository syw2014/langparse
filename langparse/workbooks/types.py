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
class CandidateRegion:
    source_ref: SourceRef
    cell_refs: list[str] = field(default_factory=list)
    kind: str = "unknown"
    confidence: float = 1.0
    features: StructuredData = field(default_factory=dict)
    diagnostics: list[StructuredData] = field(default_factory=list)


@dataclass
class HeaderColumn:
    column_id: str
    coordinate: str
    path: list[str] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    inferred_type: str = "unknown"
    unit: str | None = None


@dataclass
class LogicalRow:
    row_id: str
    source_ref: SourceRef
    role: str
    values: list[Any] = field(default_factory=list)
    source_cells: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class TableFragment:
    fragment_id: str
    source_ref: SourceRef
    page_number: int | None = None
    total_pages: int | None = None
    title_row_numbers: list[int] = field(default_factory=list)
    context_row_numbers: list[int] = field(default_factory=list)
    header_row_numbers: list[int] = field(default_factory=list)
    confidence: float = 1.0
    diagnostics: list[StructuredData] = field(default_factory=list)


@dataclass
class TableSection:
    section_id: str
    title: str
    source_ref: SourceRef
    row_ids: list[str] = field(default_factory=list)
    parent_path: list[str] = field(default_factory=list)


@dataclass
class LogicalTable:
    table_id: str
    title: str = ""
    context: list[str] = field(default_factory=list)
    columns: list[HeaderColumn] = field(default_factory=list)
    rows: list[LogicalRow] = field(default_factory=list)
    fragments: list[TableFragment] = field(default_factory=list)
    sections: list[TableSection] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    confidence: float = 1.0
    diagnostics: list[StructuredData] = field(default_factory=list)


@dataclass
class WorkbookBlock:
    block_id: str
    kind: str
    source_refs: list[SourceRef] = field(default_factory=list)
    cell_refs: list[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: StructuredData = field(default_factory=dict)
    diagnostics: list[StructuredData] = field(default_factory=list)
    logical_table: LogicalTable | None = None


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
    snapshot: WorkbookSnapshot | None = None
    metadata: StructuredData = field(default_factory=dict)
