"""Lossless workbook facts and structural intermediate representation."""

from langparse.workbooks.adapters import OOXMLWorkbookAdapter, WorkbookAdapter
from langparse.workbooks.assembly import assemble_baseline, assemble_workbook
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.regions import detect_candidate_regions
from langparse.workbooks.tables import interpret_logical_table
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
    "assemble_workbook",
    "compatibility_pages",
    "detect_candidate_regions",
    "interpret_logical_table",
    "render_workbook_markdown",
    "stable_id",
]
