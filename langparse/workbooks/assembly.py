from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

from langparse.types import ParseDiagnostics
from langparse.workbooks.blocks import (
    interpret_form_block,
    interpret_matrix_block,
    interpret_text_block,
)
from langparse.workbooks.classification import classify_candidate_region
from langparse.workbooks.continuation import link_table_continuations
from langparse.workbooks.regions import detect_candidate_regions
from langparse.workbooks.tables import interpret_logical_table
from langparse.workbooks.types import (
    CellSnapshot,
    LogicalTable,
    SheetIR,
    SourceRef,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)


def assemble_workbook(snapshot: WorkbookSnapshot) -> tuple[WorkbookIR, ParseDiagnostics]:
    """Classify and interpret candidate regions with local raw-grid fallback."""

    workbook_ir, diagnostics = assemble_baseline(snapshot)
    block_counts: Counter[str] = Counter()
    ambiguous_regions = []
    for sheet, sheet_ir in zip(snapshot.sheets, workbook_ir.sheets, strict=True):
        semantic_blocks: list[WorkbookBlock] = []
        for candidate in detect_candidate_regions(sheet):
            try:
                classification = classify_candidate_region(sheet, candidate)
                block = _block_for_candidate(
                    snapshot.source,
                    sheet,
                    candidate,
                    classification,
                )
            except Exception as exc:
                block = _unclassified_block(
                    snapshot.source,
                    candidate,
                    confidence=0.0,
                    reason_codes=["semantic_block_fallback"],
                    extra_diagnostic={"error_type": type(exc).__name__},
                )
            if block.kind == "unclassified":
                reason_codes = [
                    diagnostic["reason_code"]
                    for diagnostic in block.diagnostics
                    if "reason_code" in diagnostic
                ]
                ambiguous_regions.append(
                    {
                        "sheet_name": sheet.name,
                        "range": candidate.source_ref.range,
                        "candidate_kind": "unclassified",
                        "confidence": block.confidence,
                        "reason_codes": reason_codes,
                    }
                )
            semantic_blocks.append(block)
            block_counts[block.kind] += 1
        sheet_ir.blocks = semantic_blocks

    diagnostics.block_count_by_kind = dict(sorted(block_counts.items()))
    diagnostics.ambiguous_regions = ambiguous_regions
    try:
        groups, candidates = link_table_continuations(snapshot, workbook_ir)
    except Exception as exc:
        diagnostics.warnings.append(
            f"cross_sheet_continuation_fallback:{type(exc).__name__}"
        )
    else:
        workbook_ir.table_continuations = groups
        diagnostics.continuation_candidates = candidates
        ambiguous_count = sum(item["status"] == "ambiguous" for item in candidates)
        if ambiguous_count:
            diagnostics.warnings.append(
                f"Workbook contains {ambiguous_count} ambiguous continuation candidates"
            )
    _update_coverage(snapshot, workbook_ir, diagnostics)
    validity_ratio, invalid_refs = validate_workbook_source_refs(snapshot, workbook_ir)
    diagnostics.source_ref_validity_ratio = validity_ratio
    if invalid_refs:
        diagnostics.status = "partial"
        diagnostics.warnings.append(
            f"Workbook IR contains {len(invalid_refs)} invalid source refs: {invalid_refs[:10]}"
        )
    return workbook_ir, diagnostics


def _block_for_candidate(snapshot_source, sheet, candidate, classification):
    common = {
        "block_id": stable_id(
            "block", snapshot_source, candidate.source_ref.key, classification.kind
        ),
        "kind": classification.kind,
        "source_refs": [candidate.source_ref],
        "cell_refs": candidate.cell_refs,
        "confidence": classification.confidence,
        "metadata": {
            "view": "raw_grid"
            if classification.kind == "unclassified"
            else f"semantic_{classification.kind}",
            "cell_count": len(candidate.cell_refs),
            "features": asdict(classification.features),
            "reason_codes": list(classification.reason_codes),
        },
        "diagnostics": [
            {"reason_code": reason_code} for reason_code in classification.reason_codes
        ],
    }
    if classification.kind == "logical_table":
        table = interpret_logical_table(sheet, candidate)
        common["confidence"] = min(classification.confidence, table.confidence)
        return WorkbookBlock(**common, logical_table=table)
    if classification.kind == "form":
        return WorkbookBlock(
            **common,
            form=interpret_form_block(sheet, candidate, classification),
        )
    if classification.kind == "matrix":
        return WorkbookBlock(
            **common,
            matrix=interpret_matrix_block(sheet, candidate, classification),
        )
    if classification.kind == "text":
        return WorkbookBlock(
            **common,
            text=interpret_text_block(sheet, candidate, classification),
        )
    return WorkbookBlock(**common)


def _unclassified_block(
    snapshot_source,
    candidate,
    *,
    confidence,
    reason_codes,
    extra_diagnostic=None,
):
    diagnostics = [{"reason_code": reason_code} for reason_code in reason_codes]
    if extra_diagnostic:
        diagnostics[0].update(extra_diagnostic)
    return WorkbookBlock(
        block_id=stable_id("block", snapshot_source, candidate.source_ref.key, "unclassified"),
        kind="unclassified",
        source_refs=[candidate.source_ref],
        cell_refs=candidate.cell_refs,
        confidence=confidence,
        metadata={
            "view": "raw_grid",
            "cell_count": len(candidate.cell_refs),
            "reason_codes": list(reason_codes),
        },
        diagnostics=diagnostics,
    )


def validate_workbook_source_refs(
    snapshot: WorkbookSnapshot,
    workbook_ir: WorkbookIR,
) -> tuple[float, list[str]]:
    """Return the ratio of derived refs bounded by an existing source Sheet."""

    sheet_bounds = {
        sheet.name: range_boundaries(sheet.used_range or _range_for_coordinates(list(sheet.cells)))
        for sheet in snapshot.sheets
        if sheet.used_range or sheet.cells
    }
    refs = []
    for sheet_ir in workbook_ir.sheets:
        for block in sheet_ir.blocks:
            refs.extend(block.source_refs)
            if block.logical_table is not None:
                refs.extend(_logical_table_source_refs(block.logical_table))
            if block.form is not None:
                refs.extend(block.form.source_refs)
                refs.extend(ref for field in block.form.fields for ref in field.label_source_refs)
                refs.extend(ref for field in block.form.fields for ref in field.value_source_refs)
                refs.extend(ref for line in block.form.free_text for ref in line.source_refs)
            if block.matrix is not None:
                refs.extend(block.matrix.source_refs)
                refs.extend(
                    ref for header in block.matrix.row_headers for ref in header.source_refs
                )
                refs.extend(
                    ref for header in block.matrix.column_headers for ref in header.source_refs
                )
                refs.extend(
                    ref for row in block.matrix.value_source_refs for ref in row if ref is not None
                )
            if block.text is not None:
                refs.extend(block.text.source_refs)
                refs.extend(ref for line in block.text.lines for ref in line.source_refs)

    for continuation in workbook_ir.table_continuations:
        refs.extend(_logical_table_source_refs(continuation.logical_table))
        refs.extend(continuation.source_refs)

    invalid = sorted({ref.key for ref in refs if not _valid_source_ref(ref, sheet_bounds)})
    invalid_count = sum(not _valid_source_ref(ref, sheet_bounds) for ref in refs)
    ratio = (len(refs) - invalid_count) / len(refs) if refs else 1.0
    return ratio, invalid


def _logical_table_source_refs(table: LogicalTable) -> list[SourceRef]:
    return [
        *table.source_refs,
        *(ref for column in table.columns for ref in column.source_refs),
        *(row.source_ref for row in table.rows),
        *(fragment.source_ref for fragment in table.fragments),
        *(section.source_ref for section in table.sections),
    ]


def _valid_source_ref(ref: SourceRef, sheet_bounds) -> bool:
    bounds = sheet_bounds.get(ref.sheet_name)
    if bounds is None:
        return False
    min_col, min_row, max_col, max_row = range_boundaries(ref.range)
    sheet_min_col, sheet_min_row, sheet_max_col, sheet_max_row = bounds
    return (
        sheet_min_col <= min_col <= max_col <= sheet_max_col
        and sheet_min_row <= min_row <= max_row <= sheet_max_row
    )


def _update_coverage(snapshot, workbook_ir, diagnostics):
    source_refs = {
        f"{sheet.name}!{coordinate}"
        for sheet in snapshot.sheets
        for coordinate, cell in sheet.cells.items()
        if _is_assignable_cell(cell)
    }
    assigned_refs = {
        f"{sheet_ir.name}!{coordinate}"
        for sheet_ir in workbook_ir.sheets
        for block in sheet_ir.blocks
        for coordinate in block.cell_refs
    }
    diagnostics.coverage_ratio = (
        len(source_refs & assigned_refs) / len(source_refs) if source_refs else 1.0
    )
    diagnostics.reconstruction_passed = source_refs == assigned_refs
    if not diagnostics.reconstruction_passed:
        diagnostics.status = "partial"


def assemble_baseline(snapshot: WorkbookSnapshot) -> tuple[WorkbookIR, ParseDiagnostics]:
    """Create a lossless raw-grid IR before any semantic table interpretation."""

    sheet_irs: list[SheetIR] = []
    source_cell_keys: set[str] = set()
    assigned_cell_keys: set[str] = set()
    block_counts: Counter[str] = Counter()

    for sheet in snapshot.sheets:
        cell_refs = sorted(
            (coordinate for coordinate, cell in sheet.cells.items() if _is_assignable_cell(cell)),
            key=coordinate_to_tuple,
        )
        blocks: list[WorkbookBlock] = []
        if cell_refs:
            source_range = sheet.used_range or _range_for_coordinates(cell_refs)
            source_ref = SourceRef(sheet_name=sheet.name, range=source_range)
            block = WorkbookBlock(
                block_id=stable_id("block", snapshot.source, source_ref.key, "unclassified"),
                kind="unclassified",
                source_refs=[source_ref],
                cell_refs=cell_refs,
                metadata={"view": "raw_grid", "cell_count": len(cell_refs)},
            )
            blocks.append(block)
            block_counts[block.kind] += 1

        sheet_irs.append(
            SheetIR(
                sheet_id=stable_id("sheet", snapshot.source, str(sheet.index), sheet.name),
                name=sheet.name,
                index=sheet.index,
                blocks=blocks,
                visibility=sheet.visibility,
                metadata={
                    "used_range": sheet.used_range,
                    "print_area": sheet.print_area,
                    "merged_ranges": sheet.merged_ranges,
                    "object_count": len(sheet.objects),
                },
            )
        )

        qualified_refs = {f"{sheet.name}!{coordinate}" for coordinate in cell_refs}
        source_cell_keys.update(qualified_refs)
        assigned_cell_keys.update(qualified_refs if blocks else set())

    reconstruction_passed = assigned_cell_keys == source_cell_keys
    coverage_ratio = (
        len(assigned_cell_keys & source_cell_keys) / len(source_cell_keys)
        if source_cell_keys
        else 1.0
    )
    warnings = list(snapshot.metadata.get("warnings", []))
    if not reconstruction_passed:
        missing = sorted(source_cell_keys - assigned_cell_keys)
        warnings.append(f"Workbook IR omitted {len(missing)} source cells: {missing[:10]}")

    diagnostics = ParseDiagnostics(
        status="success" if reconstruction_passed and coverage_ratio == 1.0 else "partial",
        coverage_ratio=coverage_ratio,
        reconstruction_passed=reconstruction_passed,
        block_count_by_kind=dict(sorted(block_counts.items())),
        unsupported_features=list(snapshot.metadata.get("unsupported_features", [])),
        warnings=warnings,
    )
    workbook_ir = WorkbookIR(
        kind="workbook",
        workbook_id=stable_id("workbook", snapshot.source, snapshot.filename),
        source=snapshot.source,
        sheets=sheet_irs,
        filename=snapshot.filename,
        snapshot=snapshot,
        metadata={"snapshot": snapshot.metadata},
    )
    return workbook_ir, diagnostics


def _is_assignable_cell(cell: CellSnapshot) -> bool:
    return any(
        (
            cell.raw_value is not None,
            cell.formula is not None,
            cell.comment is not None,
            cell.hyperlink is not None,
            cell.merge_anchor is not None,
        )
    )


def _range_for_coordinates(coordinates: list[str]) -> str:
    positions = [coordinate_to_tuple(coordinate) for coordinate in coordinates]
    rows = [row for row, _ in positions]
    columns = [column for _, column in positions]
    return (
        f"{get_column_letter(min(columns))}{min(rows)}:{get_column_letter(max(columns))}{max(rows)}"
    )
