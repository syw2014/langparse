"""Lossless workbook facts and structural intermediate representation."""

from langparse.workbooks.adapters import OOXMLWorkbookAdapter, WorkbookAdapter
from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.types import (
    CellSnapshot,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)

__all__ = [
    "CellSnapshot",
    "OOXMLWorkbookAdapter",
    "SheetIR",
    "SheetSnapshot",
    "SourceRef",
    "WorkbookBlock",
    "WorkbookAdapter",
    "WorkbookIR",
    "WorkbookSnapshot",
    "assemble_baseline",
    "compatibility_pages",
    "render_workbook_markdown",
    "stable_id",
]
