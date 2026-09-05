from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from openpyxl.utils import get_column_letter, range_boundaries

from langparse.workbooks.modeling import RegionChoice
from langparse.workbooks.modeling.types import REGION_RULE_VERSION
from langparse.workbooks.types import CandidateRegion, SheetSnapshot, stable_id

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


@dataclass(frozen=True)
class RegionAssessment:
    deterministic: BlockClassification
    choices: tuple[RegionChoice, ...]
    ambiguous: bool
    ambiguity_codes: tuple[str, ...]


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

    features = features if features is not None else extract_region_features(sheet, candidate)
    values, _ = _region_grid(sheet, candidate)
    return _classify_region(values, features, candidate.reason_codes)


def assess_candidate_region(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
) -> RegionAssessment:
    """Assess a region and register only locally compatible alternative kinds."""

    features = extract_region_features(sheet, candidate)
    feature_digest = _structural_feature_digest(features)
    values, _ = _region_grid(sheet, candidate)
    deterministic = _classify_region(values, features, candidate.reason_codes)
    choices = [
        RegionChoice(
            choice_id=_choice_id(
                candidate,
                feature_digest,
                deterministic.kind,
                deterministic.reason_codes[0],
            ),
            kind=deterministic.kind,
            local_score=deterministic.confidence,
            reason_codes=tuple(deterministic.reason_codes),
        )
    ]
    if deterministic.kind != "unclassified":
        return RegionAssessment(
            deterministic=deterministic,
            choices=tuple(choices),
            ambiguous=False,
            ambiguity_codes=(),
        )

    seen_kinds = {deterministic.kind}
    for kind, score, reason_code in _weak_choice_kinds(features):
        if kind in seen_kinds:
            continue
        choices.append(
            RegionChoice(
                choice_id=_choice_id(candidate, feature_digest, kind, reason_code),
                kind=kind,
                local_score=score,
                reason_codes=(reason_code,),
            )
        )
        seen_kinds.add(kind)

    ambiguous = len(choices) >= 2
    return RegionAssessment(
        deterministic=deterministic,
        choices=tuple(choices),
        ambiguous=ambiguous,
        ambiguity_codes=("unclassified_with_compatible_choices",) if ambiguous else (),
    )


def _classify_region(
    values: list[list[str]],
    features: RegionFeatures,
    region_reason_codes: list[str] | None = None,
) -> BlockClassification:
    """Apply the existing deterministic winner rules to precomputed facts."""

    if "native_table_anchor" in (region_reason_codes or []):
        return BlockClassification(
            "logical_table",
            0.98,
            ["native_table_anchor"],
            features,
        )
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


def _weak_choice_kinds(features: RegionFeatures) -> list[tuple[str, float, str]]:
    choices = []
    if (
        features.row_count >= 2
        and features.column_count >= 2
        and max(features.nonempty_by_row, default=0) >= 2
    ):
        choices.append(("logical_table", 0.4, "weak_row_column_structure"))
    if features.column_count >= 2 and features.label_value_pairs >= 1:
        choices.append(("form", 0.4, "weak_label_value_pairs"))
    if features.numeric_grid_rows >= 1 and features.numeric_grid_columns >= 1:
        choices.append(("matrix", 0.4, "weak_numeric_axes"))
    if features.occupied_count >= 2 and features.text_ratio >= 0.6:
        choices.append(("text", 0.4, "weak_text_region"))
    return choices


def _structural_feature_digest(features: RegionFeatures) -> str:
    payload = json.dumps(
        asdict(features),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return stable_id("region_features", payload)


def _choice_id(
    candidate: CandidateRegion,
    feature_digest: str,
    kind: str,
    reason_code: str,
) -> str:
    return stable_id(
        "region_choice",
        REGION_RULE_VERSION,
        candidate.source_ref.key,
        feature_digest,
        kind,
        reason_code,
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
