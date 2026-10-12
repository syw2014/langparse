"""Optional complete fact truth; absent truth is never scored as perfect."""

from dataclasses import dataclass
from typing import Any

FACT_METRICS = frozenset(
    {
        "formula_accuracy",
        "named_range_accuracy",
        "excel_table_accuracy",
        "visibility_accuracy",
        "dependency_precision",
        "dependency_recall",
    }
)


@dataclass(frozen=True)
class WorkbookFactTruth:
    formulas: tuple[tuple[str, str], ...]
    defined_names: tuple[tuple[str, str, str | None], ...]
    tables: tuple[tuple[str, str, tuple[str, ...]], ...]
    sheet_visibility: tuple[tuple[str, str], ...]
    dependencies: tuple[tuple[str, str | None, str, str], ...]


def load_fact_truth(data: Any, sheets: set[str]) -> WorkbookFactTruth:
    import re

    keys = {"formulas", "defined_names", "tables", "sheet_visibility", "dependencies"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("Fact truth keys do not match schema")

    def rows(key, fields):
        items = data[key]
        if not isinstance(items, list):
            raise ValueError(f"{key} truth must be a list")
        for item in items:
            if not isinstance(item, dict) or set(item) != set(fields):
                raise ValueError(f"{key} truth keys do not match schema")
        return items

    def text(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Fact truth text must be nonempty")
        return value

    def source(value):
        from openpyxl.utils.cell import range_boundaries

        value = text(value)
        name, separator, cell_range = value.rpartition("!")
        if (
            not separator
            or name not in sheets
            or not re.fullmatch(r"[A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?", cell_range)
        ):
            raise ValueError("Fact truth source must identify a known sheet and finite range")
        left, top, right, bottom = range_boundaries(cell_range)
        if not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576):
            raise ValueError("Fact truth source is out of bounds")
        return value

    formulas = tuple(
        (source(r["source_ref"]), text(r["formula"]))
        for r in rows("formulas", ("source_ref", "formula"))
    )
    names = []
    for r in rows("defined_names", ("name", "definition", "scope_sheet")):
        scope = r["scope_sheet"]
        if scope is not None and (not isinstance(scope, str) or scope not in sheets):
            raise ValueError("Named range scope must identify a known sheet")
        names.append((text(r["name"]), text(r["definition"]), scope))
    tables = []
    for r in rows("tables", ("name", "source_ref", "columns")):
        if not isinstance(r["columns"], list):
            raise ValueError("Table truth columns must be a list")
        tables.append(
            (text(r["name"]), source(r["source_ref"]), tuple(text(c) for c in r["columns"]))
        )
    visibility = []
    for r in rows("sheet_visibility", ("sheet", "state")):
        if r["sheet"] not in sheets or r["state"] not in {"visible", "hidden", "veryHidden"}:
            raise ValueError("Invalid sheet visibility truth")
        visibility.append((r["sheet"], r["state"]))
    edges = []
    for r in rows("dependencies", ("dependent", "target", "status", "reference")):
        if r["status"] not in {
            "resolved",
            "external",
            "unresolved",
            "unsupported",
            "dynamic",
            "circular",
        }:
            raise ValueError("Invalid dependency status truth")
        target = source(r["target"]) if r["target"] is not None else None
        if r["status"] != "resolved" and target is not None:
            raise ValueError("Unresolved dependency cannot have a target")
        edges.append((source(r["dependent"]), target, r["status"], text(r["reference"])))
    groups = (formulas, tuple(names), tuple(tables), tuple(visibility), tuple(edges))
    if any(len(items) != len(set(items)) for items in groups):
        raise ValueError("Duplicate fact truth")
    return WorkbookFactTruth(*groups)


def evaluate_fact_truth(truth, workbook) -> dict[str, float | None]:
    from collections import Counter

    if truth is None:
        return dict.fromkeys(FACT_METRICS)
    snapshot = workbook.snapshot
    facts = snapshot.reference_facts if snapshot else None
    observed = (
        [(f.source_ref.key, f.formula) for f in facts.formulas] if facts else [],
        [(n.name, n.definition, n.scope_sheet) for n in facts.defined_names] if facts else [],
        [(t.name, t.source_ref.key, tuple(t.columns)) for t in facts.tables] if facts else [],
        [(s.name, s.visibility) for s in snapshot.sheets] if snapshot else [],
    )
    scores = {}
    for name, expected, actual in zip(
        ("formula_accuracy", "named_range_accuracy", "excel_table_accuracy", "visibility_accuracy"),
        (truth.formulas, truth.defined_names, truth.tables, truth.sheet_visibility),
        observed,
        strict=True,
    ):
        want, got = Counter(expected), Counter(actual)
        denominator = max(want.total(), got.total())
        scores[name] = sum((want & got).values()) / denominator if denominator else 1.0
    edges = (
        [
            (e.dependent.key, e.target.key if e.target else None, e.status, e.reference)
            for e in workbook.lineage.edges
        ]
        if workbook.lineage
        else []
    )
    want, got = Counter(truth.dependencies), Counter(edges)
    correct = sum((want & got).values())
    scores["dependency_precision"] = correct / got.total() if got else (0.0 if want else 1.0)
    scores["dependency_recall"] = correct / want.total() if want else (0.0 if got else 1.0)
    return scores
