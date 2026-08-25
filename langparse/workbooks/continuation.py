"""Deterministic evidence scoring for cross-Sheet table continuations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from statistics import median

from langparse.workbooks.types import HeaderColumn, LogicalTable, SheetSnapshot

_PAGE_MARKER_RE = re.compile(r"第\s*\d+\s*页\s*共\s*\d+\s*页")
_CONTINUATION_SUFFIX_RE = re.compile(r"\s*(?:续表|续|continued)\s*$")
_PARENTHESIZED_CONTINUATION_SUFFIX_RE = re.compile(r"\s*\(\s*(?:续表|续|continued)\s*\)\s*$")
_SHEET_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")
_PRESENTATION_ROLES = {
    "title",
    "context",
    "header",
    "repeated_title",
    "repeated_context",
    "repeated_header",
}


@dataclass(frozen=True)
class ContinuationCandidate:
    left_sheet: str
    right_sheet: str
    left_table_id: str
    right_table_id: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    terminal_reason_codes: tuple[str, ...] = ()


def score_continuation(
    left_sheet: SheetSnapshot,
    left_table: LogicalTable,
    right_sheet: SheetSnapshot,
    right_table: LogicalTable,
) -> ContinuationCandidate | None:
    """Score the explainable evidence that two table fragments continue each other."""

    if header_fingerprint(left_table) != header_fingerprint(right_table):
        return None

    left_title = _normalize_title(left_table.title)
    right_title = _normalize_title(right_table.title)
    terminal = _terminal_reason_codes(left_table, left_title, right_table, right_title)

    score = 0.35
    reasons = ["header_fingerprint_match"]
    if _has_valid_page_sequence(left_table, right_table):
        score += 0.35
        reasons.append("print_page_sequence")
    if left_title and left_title == right_title:
        score += 0.25
        reasons.append("title_match")
    if _has_sequential_sheet_names(left_sheet.name, right_sheet.name):
        score += 0.25
        reasons.append("sheet_name_sequence")
    if _has_compatible_widths(left_sheet, left_table, right_sheet, right_table):
        score += 0.15
        reasons.append("column_width_compatibility")
    if _has_compatible_units(left_table, right_table):
        score += 0.10
        reasons.append("unit_compatibility")

    return ContinuationCandidate(
        left_sheet=left_sheet.name,
        right_sheet=right_sheet.name,
        left_table_id=left_table.table_id,
        right_table_id=right_table.table_id,
        confidence=round(min(score, 1.0), 4),
        reason_codes=tuple(reasons),
        terminal_reason_codes=tuple(terminal),
    )


def header_fingerprint(table: LogicalTable) -> tuple[tuple[str, ...], ...]:
    """Return the positional, normalized schema required for a continuation."""

    fingerprint = []
    for index, column in enumerate(table.columns):
        path = tuple(_normalize_text(part) for part in column.path if _normalize_text(part))
        fingerprint.append(path or (f"<empty:{index}>",))
    return tuple(fingerprint)


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _normalize_title(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = _PAGE_MARKER_RE.sub("", normalized).strip()
    normalized = _PARENTHESIZED_CONTINUATION_SUFFIX_RE.sub("", normalized).strip()
    return _CONTINUATION_SUFFIX_RE.sub("", normalized).strip()


def _terminal_reason_codes(
    left_table: LogicalTable,
    left_title: str,
    right_table: LogicalTable,
    right_title: str,
) -> list[str]:
    terminal = []
    if _ends_with_total(left_table):
        terminal.append("terminal_total")
    if left_title and right_title and left_title != right_title:
        terminal.append("title_mismatch")
    if _page_metadata_conflicts(left_table, right_table):
        terminal.append("page_sequence_conflict")
    return terminal


def _ends_with_total(table: LogicalTable) -> bool:
    for row in reversed(table.rows):
        if row.role not in _PRESENTATION_ROLES:
            return row.role == "total"
    return False


def _page_metadata(
    left_table: LogicalTable, right_table: LogicalTable
) -> tuple[int, int, int] | None:
    left_fragment = next(
        (
            fragment
            for fragment in reversed(left_table.fragments)
            if fragment.page_number is not None and fragment.total_pages is not None
        ),
        None,
    )
    right_fragment = next(
        (
            fragment
            for fragment in right_table.fragments
            if fragment.page_number is not None and fragment.total_pages is not None
        ),
        None,
    )
    if left_fragment is None or right_fragment is None:
        return None
    if left_fragment.page_number is None or left_fragment.total_pages is None:
        return None
    if right_fragment.page_number is None or right_fragment.total_pages is None:
        return None
    if left_fragment.total_pages != right_fragment.total_pages:
        return left_fragment.page_number, right_fragment.page_number, -1
    return left_fragment.page_number, right_fragment.page_number, left_fragment.total_pages


def _has_valid_page_sequence(left_table: LogicalTable, right_table: LogicalTable) -> bool:
    metadata = _page_metadata(left_table, right_table)
    return (
        metadata is not None
        and 1 <= metadata[0] < metadata[2]
        and metadata[1] == metadata[0] + 1 <= metadata[2]
    )


def _page_metadata_conflicts(left_table: LogicalTable, right_table: LogicalTable) -> bool:
    metadata = _page_metadata(left_table, right_table)
    return metadata is not None and not (
        1 <= metadata[0] < metadata[2] and metadata[1] == metadata[0] + 1 <= metadata[2]
    )


def _has_sequential_sheet_names(left_name: str, right_name: str) -> bool:
    left = _normalize_text(left_name)
    right = _normalize_text(right_name)
    if right in {f"{left}续", f"{left}续表", f"{left}continued"}:
        return True
    left_match = _SHEET_NUMBER_RE.fullmatch(left)
    right_match = _SHEET_NUMBER_RE.fullmatch(right)
    return bool(
        left_match
        and right_match
        and left_match.group(1)
        and left_match.group(1) == right_match.group(1)
        and int(right_match.group(2)) == int(left_match.group(2)) + 1
    )


def _has_compatible_widths(
    left_sheet: SheetSnapshot,
    left_table: LogicalTable,
    right_sheet: SheetSnapshot,
    right_table: LogicalTable,
) -> bool:
    paired_columns = list(zip(left_table.columns, right_table.columns, strict=True))
    if not paired_columns:
        return False
    differences = [
        _relative_width_difference(
            left_sheet.column_widths[left.coordinate], right_sheet.column_widths[right.coordinate]
        )
        for left, right in paired_columns
        if left.coordinate in left_sheet.column_widths
        and right.coordinate in right_sheet.column_widths
    ]
    return len(differences) * 2 >= len(paired_columns) and median(differences) <= 0.15


def _relative_width_difference(left_width: float, right_width: float) -> float:
    denominator = max(abs(left_width), abs(right_width))
    if denominator == 0:
        return 0.0
    return abs(left_width - right_width) / denominator


def _has_compatible_units(left_table: LogicalTable, right_table: LogicalTable) -> bool:
    paired_columns = list(zip(left_table.columns, right_table.columns, strict=True))
    if any(left.unit or right.unit for left, right in paired_columns):
        return any(
            left.unit and right.unit and _normalize_text(left.unit) == _normalize_text(right.unit)
            for left, right in paired_columns
        )
    return any(
        _unit_values(left_table, index) & _unit_values(right_table, index)
        for index, (left, right) in enumerate(paired_columns)
        if _is_unit_column(left) and _is_unit_column(right)
    )


def _is_unit_column(column: HeaderColumn) -> bool:
    return any(
        "单位" in _normalize_text(part) or "unit" in _normalize_text(part) for part in column.path
    )


def _unit_values(table: LogicalTable, column_index: int) -> set[str]:
    return {
        normalized
        for row in table.rows
        if row.role == "data" and column_index < len(row.values)
        for normalized in [_normalize_text(str(row.values[column_index]))]
        if normalized
    }
