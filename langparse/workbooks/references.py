"""Conservative Excel reference parsing; never evaluates a formula or opens a link."""

from __future__ import annotations

import re

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils import get_column_letter, range_boundaries

from langparse.workbooks.reference_types import (
    ExternalReferenceFact,
    FormulaFact,
    FormulaReference,
    ReferenceDiagnostic,
)
from langparse.workbooks.types import SourceRef, WorkbookSnapshot

_A1 = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?$")


def extract_reference_facts(snapshot: WorkbookSnapshot) -> None:
    facts = snapshot.reference_facts
    facts.formulas.clear()
    facts.external_references.clear()
    facts.diagnostics.clear()
    for sheet in snapshot.sheets:
        for cell in sheet.cells.values():
            if cell.formula is None:
                continue
            source = SourceRef(sheet.name, cell.coordinate)
            if not isinstance(cell.formula, str):
                facts.diagnostics.append(
                    ReferenceDiagnostic(
                        "unsupported_formula", "Non-text formula representation", [source]
                    )
                )
                continue
            fact = FormulaFact(source, cell.formula)
            facts.formulas.append(fact)
            try:
                tokens = Tokenizer(cell.formula).items
            except (TokenizerError, IndexError, ValueError):
                facts.diagnostics.append(
                    ReferenceDiagnostic("unsupported_formula", cell.formula, [source])
                )
                continue
            for token in tokens:
                if token.type == "FUNC" and token.subtype == "OPEN":
                    if token.value[:-1].upper().removeprefix("_XLFN.") in {"INDIRECT", "OFFSET"}:
                        facts.diagnostics.append(
                            ReferenceDiagnostic("dynamic_reference", token.value[:-1], [source])
                        )
                if token.type == "OPERAND" and token.subtype == "ERROR":
                    facts.diagnostics.append(
                        ReferenceDiagnostic("invalid_reference", token.value, [source])
                    )
                if token.type != "OPERAND" or token.subtype != "RANGE":
                    continue
                ref = _resolve(token.value, source, snapshot, set())
                fact.references.append(ref)
                if ref.external_workbook:
                    facts.external_references.append(
                        ExternalReferenceFact(ref.external_workbook, ref.reference, source)
                    )
                if ref.status not in {"resolved", "external"}:
                    facts.diagnostics.append(
                        ReferenceDiagnostic(ref.status + "_reference", ref.reference, [source])
                    )


def _resolve(text, source, snapshot, visiting):
    sheet_name, local = source.sheet_name, text
    if "!" in text:
        qualifier, local = text.rsplit("!", 1)
        sheet_name = qualifier.strip("'").replace("''", "'")
        external = re.search(r"\[([^]]+)\]", sheet_name)
        if external:
            return FormulaReference(text, "external", external_workbook=external.group(1))
        if ":" in sheet_name:
            return FormulaReference(text, "unsupported")
    canonical = next(
        (s.name for s in snapshot.sheets if s.name.casefold() == sheet_name.casefold()), None
    )
    if canonical is None:
        return FormulaReference(text, "unresolved")
    if _A1.fullmatch(local):
        normalized = local.replace("$", "").upper()
        bounds = range_boundaries(normalized)
        if (
            bounds[2] <= 16384
            and bounds[3] <= 1048576
            and bounds[0] <= bounds[2]
            and bounds[1] <= bounds[3]
        ):
            return FormulaReference(text, "resolved", [SourceRef(canonical, normalized)])
        return FormulaReference(text, "unsupported")
    names = [
        n
        for n in snapshot.reference_facts.defined_names
        if n.name.casefold() == local.casefold() and n.scope_sheet in (None, canonical)
    ]
    names.sort(key=lambda n: n.scope_sheet is None)
    if names:
        name = names[0]
        key = (name.scope_sheet, name.name.casefold())
        if key in visiting:
            return FormulaReference(text, "circular")
        # Names may contain constants or formulas. Only explicit range/name aliases resolve.
        definition = name.definition.lstrip("=")
        if re.search(r"(?i)\b(?:INDIRECT|OFFSET)\s*\(", definition):
            return FormulaReference(text, "dynamic")
        if re.fullmatch(r"(?:[+-]?\d+(?:\.\d+)?|TRUE|FALSE|\".*\")", definition, re.I):
            return FormulaReference(text, "resolved")
        resolved = _resolve(
            definition, SourceRef(canonical, source.range), snapshot, visiting | {key}
        )
        return FormulaReference(text, resolved.status, resolved.targets, resolved.external_workbook)
    if any(t.name.casefold() == local.casefold() for t in snapshot.reference_facts.tables):
        return _structured(text, local + "[#Data]", source, snapshot)
    if re.fullmatch(r"\$?[A-Za-z]+:\$?[A-Za-z]+|\$?\d+:\$?\d+", local):
        return FormulaReference(text, "unsupported")
    if "[" in local:
        return _structured(text, local, source, snapshot)
    return FormulaReference(text, "unresolved")


def _structured(text, local, source, snapshot):
    table_name = local.split("[", 1)[0]
    tables = [
        t for t in snapshot.reference_facts.tables if t.name.casefold() == table_name.casefold()
    ]
    if not table_name:
        from langparse.workbooks.lineage import overlaps

        tables = [t for t in snapshot.reference_facts.tables if overlaps(t.source_ref, source)]
    if len(tables) != 1:
        return FormulaReference(text, "unresolved")
    table = tables[0]
    left, top, right, bottom = range_boundaries(table.source_ref.range)
    parts = re.findall(r"\[([^\[\]]+)\]", local)
    selectors = [p for p in parts if p.startswith("#")]
    columns = [p.lstrip("@") for p in parts if not p.startswith("#")]
    if any(s not in {"#All", "#Data", "#Headers", "#Totals", "#This Row"} for s in selectors):
        return FormulaReference(text, "unsupported")
    if len(selectors) > 1:
        return FormulaReference(text, "unsupported")
    selector = selectors[0] if selectors else "#Data"
    if selector == "#Headers":
        bottom = top + table.header_rows - 1
    elif selector == "#Totals":
        top = bottom - table.totals_rows + 1
    elif selector != "#All":
        top += table.header_rows
        bottom -= table.totals_rows
    if selector == "#This Row" or "@" in local:
        row = range_boundaries(source.range)[1]
        if source.sheet_name != table.source_ref.sheet_name or not top <= row <= bottom:
            return FormulaReference(text, "unsupported")
        top = bottom = row
    if columns:
        indices = []
        for column in columns:
            matches = [
                i for i, name in enumerate(table.columns) if name.casefold() == column.casefold()
            ]
            if not matches:
                return FormulaReference(text, "unresolved")
            indices.append(left + matches[0])
        if len(indices) > 2 or (len(indices) == 2 and ":" not in local):
            return FormulaReference(text, "unsupported")
        left, right = indices[0], indices[-1]
    if bottom < top or right < left:
        return FormulaReference(text, "unsupported")
    target = f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"
    return FormulaReference(text, "resolved", [SourceRef(table.source_ref.sheet_name, target)])
