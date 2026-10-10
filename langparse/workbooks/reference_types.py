"""Typed source facts and evidence-bearing dependency results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langparse.workbooks.types import SourceRef


@dataclass
class ReferenceDiagnostic:
    code: str
    message: str
    source_refs: list[SourceRef] = field(default_factory=list)


@dataclass
class DefinedNameFact:
    name: str
    definition: str
    scope_sheet: str | None = None


@dataclass
class ExcelTableFact:
    name: str
    source_ref: SourceRef
    columns: list[str] = field(default_factory=list)
    header_rows: int = 1
    totals_rows: int = 0


@dataclass
class FormulaReference:
    reference: str
    status: str
    targets: list[SourceRef] = field(default_factory=list)
    external_workbook: str | None = None


@dataclass
class FormulaFact:
    source_ref: SourceRef
    formula: str
    references: list[FormulaReference] = field(default_factory=list)


@dataclass
class ExternalReferenceFact:
    workbook: str
    reference: str
    source_ref: SourceRef


@dataclass
class WorkbookReferenceFacts:
    defined_names: list[DefinedNameFact] = field(default_factory=list)
    tables: list[ExcelTableFact] = field(default_factory=list)
    formulas: list[FormulaFact] = field(default_factory=list)
    external_references: list[ExternalReferenceFact] = field(default_factory=list)
    diagnostics: list[ReferenceDiagnostic] = field(default_factory=list)


@dataclass
class DependencyEdge:
    dependent: SourceRef
    target: SourceRef | None
    reference: str
    status: str
    source_refs: list[SourceRef] = field(default_factory=list)
    external_workbook: str | None = None
