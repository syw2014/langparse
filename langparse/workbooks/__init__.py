"""Lossless workbook facts and structural intermediate representation."""

from langparse.workbooks.adapters import OOXMLWorkbookAdapter, WorkbookAdapter
from langparse.workbooks.assembly import (
    assemble_baseline,
    assemble_workbook,
    validate_workbook_source_refs,
)
from langparse.workbooks.blocks import (
    interpret_form_block,
    interpret_matrix_block,
    interpret_text_block,
)
from langparse.workbooks.regions import detect_candidate_regions
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.tables import interpret_logical_table
from langparse.workbooks.types import (
    CandidateRegion,
    CellSnapshot,
    FormBlock,
    FormField,
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    MatrixBlock,
    MatrixHeader,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    TableContinuation,
    TableFragment,
    TableSection,
    TextBlock,
    TextLine,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)

__all__ = [
    "CandidateRegion",
    "CellSnapshot",
    "FormBlock",
    "FormField",
    "HeaderColumn",
    "LogicalRow",
    "LogicalTable",
    "MatrixBlock",
    "MatrixHeader",
    "OOXMLWorkbookAdapter",
    "SheetIR",
    "SheetSnapshot",
    "SourceRef",
    "TableFragment",
    "TableSection",
    "TableContinuation",
    "TextBlock",
    "TextLine",
    "WorkbookBlock",
    "WorkbookAdapter",
    "WorkbookIR",
    "WorkbookSnapshot",
    "assemble_baseline",
    "assemble_workbook",
    "compatibility_pages",
    "detect_candidate_regions",
    "interpret_logical_table",
    "interpret_form_block",
    "interpret_matrix_block",
    "interpret_text_block",
    "render_workbook_markdown",
    "stable_id",
    "validate_workbook_source_refs",
]
