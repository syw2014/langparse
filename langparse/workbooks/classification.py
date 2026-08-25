from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.utils import get_column_letter, range_boundaries

from langparse.workbooks.types import CandidateRegion, SheetSnapshot

PAGE_RE = re.compile(r"第\s*\d+\s*页\s*共\s*\d+\s*页")


@dataclass(frozen=True)
class RegionFeatures:
    row_count: int
    column_count: int
    occupied_count: int
    density: float
    text_ratio: float
    numeric_ratio: float
    formula_ratio: float
    nonempty_by_row: tuple[int, ...]
    nonempty_by_column: tuple[int, ...]
    positive_ordinal_rows: int
    label_value_pairs: int
    label_value_coverage: float
    numeric_grid_rows: int
    numeric_grid_columns: int
    merged_title_rows: int
    long_text_rows: int
    has_page_sequence: bool
    has_stable_table_schema: bool


@dataclass(frozen=True)
class BlockClassification:
    kind: str
    confidence: float
    reason_codes: list[str]
    features: RegionFeatures


def extract_region_features(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
) -> RegionFeatures:
    """Compute deterministic, serializable signals for one candidate region."""

    values, cells = _region_grid(sheet, candidate)
    row_count = len(values)
    column_count = len(values[0]) if values else 0
    flat_values = [value for row in values for value in row if value != ""]
    semantic_count = len(flat_values)
    numeric_count = sum(_is_number(value) for value in flat_values)
    text_count = semantic_count - numeric_count
    formula_count = sum(
        cell is not None and cell.merge_anchor is None and cell.formula is not None
        for row in cells
        for cell in row
    )
    nonempty_by_row = tuple(sum(value != "" for value in row) for row in values)
    nonempty_by_column = tuple(
        sum(values[row][column] != "" for row in range(row_count)) for column in range(column_count)
    )
    positive_ordinal_rows = sum(_is_positive_integer(row[0]) for row in values[1:] if row)
    label_value_pairs = sum(_label_value_pairs(row) for row in values)
    numeric_grid_rows, numeric_grid_columns = _numeric_grid_shape(values)
    merged_title_rows = sum(
        sum(value != "" for value in value_row) == 1
        and any(cell is not None and cell.colspan > 1 for cell in cell_row)
        for value_row, cell_row in zip(values, cells, strict=True)
    )
    long_text_rows = sum(
        len(nonempty) == 1 and len(nonempty[0]) >= 20
        for row in values
        for nonempty in [[value for value in row if value]]
    )
    has_page_sequence = any(PAGE_RE.search(value) for value in flat_values)
    has_stable_table_schema = _has_stable_table_schema(
        values,
        numeric_grid_rows=numeric_grid_rows,
        numeric_grid_columns=numeric_grid_columns,
    )
    area = row_count * column_count
    return RegionFeatures(
        row_count=row_count,
        column_count=column_count,
        occupied_count=len(candidate.cell_refs),
        density=len(candidate.cell_refs) / area if area else 0.0,
        text_ratio=text_count / semantic_count if semantic_count else 0.0,
        numeric_ratio=numeric_count / semantic_count if semantic_count else 0.0,
        formula_ratio=formula_count / semantic_count if semantic_count else 0.0,
        nonempty_by_row=nonempty_by_row,
        nonempty_by_column=nonempty_by_column,
        positive_ordinal_rows=positive_ordinal_rows,
        label_value_pairs=label_value_pairs,
        label_value_coverage=label_value_pairs / row_count if row_count else 0.0,
        numeric_grid_rows=numeric_grid_rows,
        numeric_grid_columns=numeric_grid_columns,
        merged_title_rows=merged_title_rows,
        long_text_rows=long_text_rows,
        has_page_sequence=has_page_sequence,
        has_stable_table_schema=has_stable_table_schema,
    )


def classify_candidate_region(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
    features: RegionFeatures | None = None,
) -> BlockClassification:
    """Classify a region conservatively with mutually exclusive rules."""

    features = features or extract_region_features(sheet, candidate)
    values, _ = _region_grid(sheet, candidate)
    text_reason = _text_reason(features)
    if text_reason:
        return BlockClassification("text", 0.9, [text_reason], features)
    if _is_form(features):
        return BlockClassification("form", 0.9, ["stable_label_value_pairs"], features)
    if _is_matrix(values, features):
        return BlockClassification("matrix", 0.95, ["numeric_matrix_with_axes"], features)
    if _is_logical_table(features):
        reason = (
            "consistent_print_fragments"
            if features.has_page_sequence
            else "stable_header_data_schema"
        )
        return BlockClassification("logical_table", 0.9, [reason], features)
    return BlockClassification(
        "unclassified",
        0.5,
        ["insufficient_semantic_evidence"],
        features,
    )


def _region_grid(sheet: SheetSnapshot, candidate: CandidateRegion):
    min_col, min_row, max_col, max_row = range_boundaries(candidate.source_ref.range)
    values = []
    cells = []
    for row_number in range(min_row, max_row + 1):
        value_row = []
        cell_row = []
        for column_number in range(min_col, max_col + 1):
            coordinate = f"{get_column_letter(column_number)}{row_number}"
            cell = sheet.cells.get(coordinate)
            cell_row.append(cell)
            value_row.append(
                "" if cell is None or cell.merge_anchor is not None else cell.display_value.strip()
            )
        values.append(value_row)
        cells.append(cell_row)
    return values, cells


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except (TypeError, ValueError):
        return False
    return True


def _is_positive_integer(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9]\d*", value.strip()))


def _label_value_pairs(row: list[str]) -> int:
    nonempty = [(index, value) for index, value in enumerate(row) if value]
    if len(nonempty) % 2:
        return 0
    pairs = 0
    for offset in range(0, len(nonempty) - 1, 2):
        (label_index, label), (value_index, _) = nonempty[offset : offset + 2]
        if value_index == label_index + 1 and not _is_number(label):
            pairs += 1
    return pairs


def _numeric_grid_shape(values: list[list[str]]) -> tuple[int, int]:
    if len(values) < 2 or len(values[0]) < 2:
        return 0, 0
    interior = [row[1:] for row in values[1:]]
    numeric_rows = sum(
        row and all(value and _is_number(value) for value in row) for row in interior
    )
    numeric_columns = sum(
        all(
            interior[row][column] and _is_number(interior[row][column])
            for row in range(len(interior))
        )
        for column in range(len(interior[0]))
    )
    return numeric_rows, numeric_columns


def _has_stable_table_schema(
    values: list[list[str]],
    *,
    numeric_grid_rows: int,
    numeric_grid_columns: int,
) -> bool:
    if len(values) < 2 or len(values[0]) < 2:
        return False
    if numeric_grid_rows >= 2 and numeric_grid_columns >= 2:
        return False
    header = values[0]
    if not all(value and not _is_number(value) for value in header):
        return False
    widths = [sum(value != "" for value in row) for row in values[1:]]
    return bool(widths) and len(set(widths)) == 1 and widths[0] == len(header)


def _text_reason(features: RegionFeatures) -> str | None:
    if (
        features.row_count >= 2
        and features.column_count == 1
        and features.text_ratio == 1.0
        and features.positive_ordinal_rows == 0
    ):
        return "single_column_text"
    if (
        features.row_count >= 2
        and features.column_count >= 2
        and features.text_ratio >= 0.8
        and features.numeric_grid_rows < 2
        and features.positive_ordinal_rows == 0
        and features.label_value_pairs < 2
        and not features.has_stable_table_schema
        and (features.merged_title_rows >= 1 or features.long_text_rows >= 1)
    ):
        return "presentation_text_region"
    return None


def _is_form(features: RegionFeatures) -> bool:
    return (
        features.label_value_pairs >= 2
        and features.label_value_coverage >= 0.5
        and not features.has_stable_table_schema
        and features.numeric_grid_columns < 2
        and features.positive_ordinal_rows == 0
    )


def _is_matrix(values: list[list[str]], features: RegionFeatures) -> bool:
    if features.numeric_grid_rows < 2 or features.numeric_grid_columns < 2:
        return False
    top_axis = values and all(value and not _is_number(value) for value in values[0][1:])
    left_axis = all(row[0] and not _is_number(row[0]) for row in values[1:])
    return bool(top_axis and left_axis)


def _is_logical_table(features: RegionFeatures) -> bool:
    return bool(
        features.has_page_sequence
        or features.has_stable_table_schema
        or (
            features.row_count >= 2
            and features.column_count >= 2
            and features.positive_ordinal_rows >= 1
        )
    )
