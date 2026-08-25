from __future__ import annotations

from collections import Counter

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple

from langparse.types import ParseDiagnostics
from langparse.workbooks.types import (
    CellSnapshot,
    SheetIR,
    SourceRef,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)


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
