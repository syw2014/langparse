"""Lossless workbook facts and structural intermediate representation."""

from langparse.workbooks.adapters import OOXMLWorkbookAdapter, WorkbookAdapter
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
    "stable_id",
]
