"""Lossless workbook facts and structural intermediate representation."""

from langparse.workbooks.adapters import OOXMLWorkbookAdapter, WorkbookAdapter
from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.types import (
    CandidateRegion,
    CellSnapshot,
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    TableFragment,
    TableSection,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)

__all__ = [
    "CandidateRegion",
    "CellSnapshot",
    "HeaderColumn",
    "LogicalRow",
    "LogicalTable",
    "OOXMLWorkbookAdapter",
    "SheetIR",
    "SheetSnapshot",
    "SourceRef",
    "TableFragment",
    "TableSection",
    "WorkbookBlock",
    "WorkbookAdapter",
    "WorkbookIR",
    "WorkbookSnapshot",
    "assemble_baseline",
    "compatibility_pages",
    "render_workbook_markdown",
    "stable_id",
]
