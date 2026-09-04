from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from langparse.types import ParsedDocumentResult
from langparse.workbooks.quality.schema import WorkbookExpectation
from langparse.workbooks.types import SourceRef, WorkbookIR

WORKBOOK_QUALITY_METRIC_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkbookQualityMetrics:
    block_precision: float
    block_recall: float
    header_path_accuracy: float | None
    row_role_f1: float | None
    form_field_exact_match: float | None
    matrix_axis_accuracy: float | None
    continuation_precision: float | None
    continuation_recall: float | None
    source_ref_completeness: float
    source_ref_validity_ratio: float
    cell_coverage_ratio: float
    fallback_rate: float
    object_fact_precision: float | None
    object_fact_recall: float | None
    object_semantic_recall: float | None


def evaluate_workbook_result(
    expectation: WorkbookExpectation,
    parsed: ParsedDocumentResult,
) -> WorkbookQualityMetrics:
    if not isinstance(parsed.structure, WorkbookIR):
        raise TypeError("Workbook quality evaluation requires WorkbookIR")
    workbook = parsed.structure

    expected_blocks = [
        (sheet.name, block.source_range, block.kind)
        for sheet in expectation.sheets
        for block in sheet.blocks
    ]
    observed_blocks = [
        (sheet.name, _block_range(block), block.kind)
        for sheet in workbook.sheets
        for block in sheet.blocks
    ]
    block_precision, block_recall = _precision_recall(expected_blocks, observed_blocks)

    expected_headers = [
        (sheet.name, block.source_range, header.coordinate, header.path)
        for sheet in expectation.sheets
        for block in sheet.blocks
        for header in block.headers
    ]
    observed_headers = [
        (sheet.name, _block_range(block), column.coordinate, tuple(column.path))
        for sheet in workbook.sheets
        for block in sheet.blocks
        if block.logical_table is not None
        for column in block.logical_table.columns
    ]

    expected_rows = [
        (sheet.name, row.source_range, row.role)
        for sheet in expectation.sheets
        for block in sheet.blocks
        for row in block.rows
    ]
    observed_rows = [
        (sheet.name, row.source_ref.range, row.role)
        for sheet in workbook.sheets
        for block in sheet.blocks
        if block.logical_table is not None
        for row in block.logical_table.rows
    ]

    expected_fields = [
        (sheet.name, block.source_range, label, _stable_value(value))
        for sheet in expectation.sheets
        for block in sheet.blocks
        for label, value in block.form_fields
    ]
    observed_fields = [
        (sheet.name, _block_range(block), field.label, _stable_value(field.value))
        for sheet in workbook.sheets
        for block in sheet.blocks
        if block.form is not None
        for field in block.form.fields
    ]

    expected_axes = [
        (sheet.name, block.source_range, axis, value)
        for sheet in expectation.sheets
        for block in sheet.blocks
        for axis, values in (
            ("row", block.matrix_axes.rows),
            ("column", block.matrix_axes.columns),
        )
        for value in values
    ]
    observed_axes = [
        (sheet.name, _block_range(block), axis, header.value)
        for sheet in workbook.sheets
        for block in sheet.blocks
        if block.matrix is not None
        for axis, headers in (
            ("row", block.matrix.row_headers),
            ("column", block.matrix.column_headers),
        )
        for header in headers
    ]

    expected_continuations = list(expectation.continuations)
    observed_continuations = [
        tuple(ref.key for ref in continuation.source_refs)
        for continuation in workbook.table_continuations
    ]
    continuation_precision, continuation_recall = _optional_precision_recall(
        expected_continuations,
        observed_continuations,
    )

    available_refs = _collect_source_refs(workbook)
    required_refs = set(expectation.required_source_refs)
    source_ref_completeness = (
        len(required_refs & available_refs) / len(required_refs) if required_refs else 1.0
    )

    expected_objects = [(item.sheet_name, item.kind, item.anchor) for item in expectation.objects]
    observed_object_facts = [
        (sheet.name, str(item.get("kind")), str(item.get("anchor")))
        for sheet in (workbook.snapshot.sheets if workbook.snapshot is not None else [])
        for item in sheet.objects
        if item.get("kind") is not None and item.get("anchor") is not None
    ]
    observed_semantic_objects = [
        (sheet.name, block.kind, str(block.metadata.get("anchor")))
        for sheet in workbook.sheets
        for block in sheet.blocks
        if block.kind in {"chart", "image"} and block.metadata.get("anchor") is not None
    ]
    object_fact_precision, object_fact_recall = _optional_precision_recall(
        expected_objects,
        observed_object_facts,
    )
    _, object_semantic_recall = _optional_precision_recall(
        expected_objects,
        observed_semantic_objects,
    )

    block_count = sum(len(sheet.blocks) for sheet in workbook.sheets)
    fallback_count = sum(
        block.kind == "unclassified" or not block.source_refs
        for sheet in workbook.sheets
        for block in sheet.blocks
    )
    diagnostics = parsed.diagnostics
    return WorkbookQualityMetrics(
        block_precision=block_precision,
        block_recall=block_recall,
        header_path_accuracy=_set_accuracy(expected_headers, observed_headers),
        row_role_f1=_set_f1(expected_rows, observed_rows),
        form_field_exact_match=_set_accuracy(expected_fields, observed_fields),
        matrix_axis_accuracy=_set_accuracy(expected_axes, observed_axes),
        continuation_precision=continuation_precision,
        continuation_recall=continuation_recall,
        source_ref_completeness=source_ref_completeness,
        source_ref_validity_ratio=(
            diagnostics.source_ref_validity_ratio if diagnostics is not None else 0.0
        ),
        cell_coverage_ratio=diagnostics.coverage_ratio if diagnostics is not None else 0.0,
        fallback_rate=fallback_count / block_count if block_count else 0.0,
        object_fact_precision=object_fact_precision,
        object_fact_recall=object_fact_recall,
        object_semantic_recall=object_semantic_recall,
    )


def _precision_recall(expected: Iterable[Any], observed: Iterable[Any]) -> tuple[float, float]:
    expected_counts = Counter(expected)
    observed_counts = Counter(observed)
    matched = sum((expected_counts & observed_counts).values())
    expected_total = expected_counts.total()
    observed_total = observed_counts.total()
    precision = matched / observed_total if observed_total else float(not expected_total)
    recall = matched / expected_total if expected_total else float(not observed_total)
    return precision, recall


def _optional_precision_recall(
    expected: Iterable[Any], observed: Iterable[Any]
) -> tuple[float | None, float | None]:
    expected = tuple(expected)
    observed = tuple(observed)
    if not expected and not observed:
        return None, None
    return _precision_recall(expected, observed)


def _set_accuracy(expected: Iterable[Any], observed: Iterable[Any]) -> float | None:
    expected_counts = Counter(expected)
    observed_counts = Counter(observed)
    if not expected_counts and not observed_counts:
        return None
    return sum((expected_counts & observed_counts).values()) / max(
        expected_counts.total(), observed_counts.total()
    )


def _set_f1(expected: Iterable[Any], observed: Iterable[Any]) -> float | None:
    expected = tuple(expected)
    observed = tuple(observed)
    if not expected and not observed:
        return None
    precision, recall = _precision_recall(expected, observed)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _block_range(block: Any) -> str:
    return block.source_refs[0].range if block.source_refs else "<missing-source-ref>"


def _stable_value(value: Any) -> str:
    return repr(value)


def _collect_source_refs(value: Any) -> set[str]:
    refs: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, SourceRef):
            refs.add(item.key)
        elif is_dataclass(item):
            for item_field in fields(item):
                if item_field.name != "snapshot":
                    visit(getattr(item, item_field.name))
        elif isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)

    visit(value)
    return refs
