from __future__ import annotations

from collections.abc import Iterable

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple

from langparse.workbooks.types import CandidateRegion, CellSnapshot, SheetSnapshot, SourceRef


def detect_candidate_regions(sheet: SheetSnapshot) -> list[CandidateRegion]:
    """Split occupied cells at complete blank row and column bands."""

    occupied = {coordinate: cell for coordinate, cell in sheet.cells.items() if _is_occupied(cell)}
    if not occupied:
        return []

    positions = {coordinate: coordinate_to_tuple(coordinate) for coordinate in occupied}
    row_bands = _consecutive_groups(row for row, _ in positions.values())
    regions: list[CandidateRegion] = []
    for min_row, max_row in row_bands:
        columns = {column for row, column in positions.values() if min_row <= row <= max_row}
        for min_column, max_column in _consecutive_groups(columns):
            cell_refs = sorted(
                (
                    coordinate
                    for coordinate, (row, column) in positions.items()
                    if min_row <= row <= max_row and min_column <= column <= max_column
                ),
                key=coordinate_to_tuple,
            )
            if not cell_refs:
                continue
            source_range = (
                f"{get_column_letter(min_column)}{min_row}:{get_column_letter(max_column)}{max_row}"
            )
            area = (max_row - min_row + 1) * (max_column - min_column + 1)
            regions.append(
                CandidateRegion(
                    source_ref=SourceRef(sheet_name=sheet.name, range=source_range),
                    cell_refs=cell_refs,
                    features={
                        "row_count": max_row - min_row + 1,
                        "column_count": max_column - min_column + 1,
                        "occupied_count": len(cell_refs),
                        "density": len(cell_refs) / area,
                    },
                )
            )
    return regions


def _is_occupied(cell: CellSnapshot) -> bool:
    return any(
        (
            cell.raw_value is not None,
            cell.formula is not None,
            cell.comment is not None,
            cell.hyperlink is not None,
            cell.merge_anchor is not None,
        )
    )


def _consecutive_groups(values: Iterable[int]) -> list[tuple[int, int]]:
    ordered = sorted(set(values))
    if not ordered:
        return []
    groups: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + 1:
            groups.append((start, previous))
            start = value
        previous = value
    groups.append((start, previous))
    return groups
