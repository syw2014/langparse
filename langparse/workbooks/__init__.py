"""Lossless workbook facts and structural intermediate representation.

Workbook algorithms depend on the optional Excel stack.  Keep those imports
lazy so the dependency-free core package and CLI discovery remain usable until
a caller actually selects Excel functionality.
"""

from importlib import import_module

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
    RegionAnchor,
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

_LAZY_EXPORTS = {
    "OOXMLWorkbookAdapter": ("langparse.workbooks.adapters", "OOXMLWorkbookAdapter"),
    "WorkbookAdapter": ("langparse.workbooks.adapters", "WorkbookAdapter"),
    "assemble_baseline": ("langparse.workbooks.assembly", "assemble_baseline"),
    "assemble_workbook": ("langparse.workbooks.assembly", "assemble_workbook"),
    "validate_workbook_source_refs": (
        "langparse.workbooks.assembly",
        "validate_workbook_source_refs",
    ),
    "interpret_form_block": ("langparse.workbooks.blocks", "interpret_form_block"),
    "interpret_matrix_block": ("langparse.workbooks.blocks", "interpret_matrix_block"),
    "interpret_text_block": ("langparse.workbooks.blocks", "interpret_text_block"),
    "detect_candidate_regions": ("langparse.workbooks.regions", "detect_candidate_regions"),
    "compatibility_pages": ("langparse.workbooks.rendering", "compatibility_pages"),
    "render_workbook_markdown": ("langparse.workbooks.rendering", "render_workbook_markdown"),
    "interpret_logical_table": ("langparse.workbooks.tables", "interpret_logical_table"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


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
    "RegionAnchor",
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
