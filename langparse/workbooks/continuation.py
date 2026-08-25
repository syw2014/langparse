"""Deterministic evidence scoring for cross-Sheet table continuations."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from statistics import median

from langparse.types import StructuredData
from langparse.workbooks.types import (
    HeaderColumn,
    LogicalTable,
    SheetIR,
    SheetSnapshot,
    TableContinuation,
    TableSection,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)

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
_REVIEW_THRESHOLD = 0.60
_AUTO_LINK_THRESHOLD = 0.85
_MIN_SCORE_LEAD = 0.10
_REPEATED_PRESENTATION_ROLES = {
    "title": "repeated_title",
    "context": "repeated_context",
    "header": "repeated_header",
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


def link_table_continuations(
    snapshot: WorkbookSnapshot,
    workbook_ir: WorkbookIR,
) -> tuple[list[TableContinuation], list[StructuredData]]:
    """Link unambiguous adjacent-Sheet table continuations and aggregate their views."""

    table_order, tables_by_id = _workbook_tables(workbook_ir)
    accepted_edges: list[ContinuationCandidate] = []
    diagnostics: list[StructuredData] = []

    for left_snapshot, left_ir, right_snapshot, right_ir in _adjacent_sheet_pairs(
        snapshot, workbook_ir
    ):
        candidates = [
            candidate
            for left_table in _logical_tables(left_ir)
            for right_table in _logical_tables(right_ir)
            for candidate in [
                score_continuation(left_snapshot, left_table, right_snapshot, right_table)
            ]
            if candidate is not None
        ]
        eligible = [
            candidate
            for candidate in candidates
            if not candidate.terminal_reason_codes and candidate.confidence >= _REVIEW_THRESHOLD
        ]
        accepted = {
            _candidate_key(candidate)
            for candidate in eligible
            if _is_mutual_unique_best(candidate, eligible)
            and candidate.confidence >= _AUTO_LINK_THRESHOLD
        }

        for candidate in candidates:
            extra_reason_codes: list[str] = []
            if candidate.terminal_reason_codes:
                status = "rejected"
                extra_reason_codes.extend(candidate.terminal_reason_codes)
            elif candidate.confidence < _REVIEW_THRESHOLD:
                continue
            elif _candidate_key(candidate) in accepted:
                status = "accepted"
                accepted_edges.append(candidate)
            else:
                status = "ambiguous"
                if candidate.confidence < _AUTO_LINK_THRESHOLD:
                    extra_reason_codes.append("below_auto_accept_threshold")
                if _has_close_competitor(candidate, eligible):
                    extra_reason_codes.append("competing_continuation_candidates")
                elif candidate.confidence >= _AUTO_LINK_THRESHOLD:
                    extra_reason_codes.append("not_mutual_unique_best")
            diagnostics.append(_candidate_diagnostic(candidate, status, extra_reason_codes))

    groups = []
    for member_table_ids, chain_edges in _continuation_chains(accepted_edges, table_order):
        member_tables = [tables_by_id[table_id] for table_id in member_table_ids]
        continuation_id = stable_id("continuation", snapshot.source, *member_table_ids)
        reason_codes = _deduplicate_reason_codes(chain_edges)
        aggregate = _aggregate_table(
            continuation_id,
            member_tables,
            chain_edges,
            reason_codes,
        )
        for index, member_table in enumerate(member_tables):
            member_table.continuation_id = continuation_id
            member_table.continuation_role = _continuation_role(index, len(member_tables))
        groups.append(
            TableContinuation(
                continuation_id=continuation_id,
                logical_table=aggregate,
                member_table_ids=list(member_table_ids),
                source_refs=deepcopy(aggregate.source_refs),
                confidence=aggregate.confidence,
                reason_codes=reason_codes,
            )
        )
    return groups, diagnostics


def _adjacent_sheet_pairs(
    snapshot: WorkbookSnapshot,
    workbook_ir: WorkbookIR,
) -> list[tuple[SheetSnapshot, SheetIR, SheetSnapshot, SheetIR]]:
    snapshot_by_index = {sheet.index: sheet for sheet in snapshot.sheets}
    ir_by_index = {sheet.index: sheet for sheet in workbook_ir.sheets}
    shared_indexes = sorted(set(snapshot_by_index) & set(ir_by_index))
    return [
        (
            snapshot_by_index[index],
            ir_by_index[index],
            snapshot_by_index[index + 1],
            ir_by_index[index + 1],
        )
        for index in shared_indexes
        if index + 1 in snapshot_by_index and index + 1 in ir_by_index
    ]


def _logical_tables(sheet_ir: SheetIR) -> list[LogicalTable]:
    return [
        block.logical_table
        for block in sheet_ir.blocks
        if block.kind == "logical_table" and block.logical_table is not None
    ]


def _workbook_tables(workbook_ir: WorkbookIR) -> tuple[dict[str, int], dict[str, LogicalTable]]:
    table_order = {}
    tables_by_id = {}
    for order, table in enumerate(
        table
        for sheet in sorted(workbook_ir.sheets, key=lambda sheet: sheet.index)
        for table in _logical_tables(sheet)
    ):
        table_order[table.table_id] = order
        tables_by_id[table.table_id] = table
    return table_order, tables_by_id


def _is_mutual_unique_best(
    candidate: ContinuationCandidate,
    candidates: list[ContinuationCandidate],
) -> bool:
    left_options = [
        option for option in candidates if option.left_table_id == candidate.left_table_id
    ]
    right_options = [
        option for option in candidates if option.right_table_id == candidate.right_table_id
    ]
    return _has_score_lead(candidate, left_options) and _has_score_lead(candidate, right_options)


def _has_score_lead(
    candidate: ContinuationCandidate,
    alternatives: list[ContinuationCandidate],
) -> bool:
    return all(
        alternative is candidate
        or round(candidate.confidence - alternative.confidence, 4) >= _MIN_SCORE_LEAD
        for alternative in alternatives
    )


def _has_close_competitor(
    candidate: ContinuationCandidate,
    candidates: list[ContinuationCandidate],
) -> bool:
    return any(
        alternative is not candidate
        and (
            alternative.left_table_id == candidate.left_table_id
            or alternative.right_table_id == candidate.right_table_id
        )
        and round(abs(candidate.confidence - alternative.confidence), 4) < _MIN_SCORE_LEAD
        for alternative in candidates
    )


def _candidate_key(candidate: ContinuationCandidate) -> tuple[str, str]:
    return candidate.left_table_id, candidate.right_table_id


def _candidate_diagnostic(
    candidate: ContinuationCandidate,
    status: str,
    extra_reason_codes: list[str],
) -> StructuredData:
    return {
        "left_table_id": candidate.left_table_id,
        "right_table_id": candidate.right_table_id,
        "left_sheet": candidate.left_sheet,
        "right_sheet": candidate.right_sheet,
        "confidence": candidate.confidence,
        "status": status,
        "reason_codes": [*candidate.reason_codes, *extra_reason_codes],
    }


def _continuation_chains(
    accepted_edges: list[ContinuationCandidate],
    table_order: dict[str, int],
) -> list[tuple[list[str], list[ContinuationCandidate]]]:
    successors = {edge.left_table_id: edge for edge in accepted_edges}
    predecessor_ids = {edge.right_table_id for edge in accepted_edges}
    heads = sorted(
        (table_id for table_id in successors if table_id not in predecessor_ids),
        key=table_order.__getitem__,
    )
    chains = []
    for head in heads:
        member_table_ids = [head]
        chain_edges = []
        current_id = head
        while current_id in successors:
            edge = successors[current_id]
            chain_edges.append(edge)
            current_id = edge.right_table_id
            member_table_ids.append(current_id)
        if len(member_table_ids) >= 2:
            chains.append((member_table_ids, chain_edges))
    return chains


def _aggregate_table(
    continuation_id: str,
    member_tables: list[LogicalTable],
    chain_edges: list[ContinuationCandidate],
    reason_codes: list[str],
) -> LogicalTable:
    copied_members = [deepcopy(table) for table in member_tables]
    aggregate = deepcopy(member_tables[0])
    aggregate.table_id = stable_id("table", continuation_id, "aggregate")
    aggregate.continuation_id = None
    aggregate.continuation_role = None
    aggregate.columns = deepcopy(copied_members[0].columns)
    aggregate.rows = []
    aggregate.fragments = []
    aggregate.sections = [
        section for copied_member in copied_members for section in copied_member.sections
    ]
    aggregate.source_refs = [
        source_ref for copied_member in copied_members for source_ref in copied_member.source_refs
    ]
    aggregate.confidence = min(
        *(table.confidence for table in member_tables),
        *(edge.confidence for edge in chain_edges),
    )
    aggregate.diagnostics = [
        {
            "reason_code": "cross_sheet_continuation",
            "continuation_id": continuation_id,
            "member_table_ids": [table.table_id for table in member_tables],
            "reason_codes": list(reason_codes),
        }
    ]

    for member_index, copied_member in enumerate(copied_members):
        if member_index:
            for aggregate_column, member_column in zip(
                aggregate.columns, copied_member.columns, strict=True
            ):
                aggregate_column.source_refs.extend(deepcopy(member_column.source_refs))
        aggregate.fragments.extend(copied_member.fragments)

    _append_aggregate_rows(aggregate, copied_members)
    return aggregate


def _append_aggregate_rows(
    aggregate: LogicalTable,
    copied_members: list[LogicalTable],
) -> None:
    active_path: list[str] = []
    active_section: TableSection | None = None
    for member_index, copied_member in enumerate(copied_members):
        member_sections_by_ref = {
            section.source_ref.key: section for section in copied_member.sections
        }
        for row in copied_member.rows:
            if member_index and row.role in _REPEATED_PRESENTATION_ROLES:
                row.role = _REPEATED_PRESENTATION_ROLES[row.role]
            if row.role == "section_header":
                active_path = list(row.section_path)
                active_section = member_sections_by_ref.get(row.source_ref.key)
                if active_section is None:
                    active_section = _section_for_path(active_path, copied_member.sections)
                if not active_path and active_section is not None:
                    active_path = [active_section.title]
            elif row.section_path:
                active_path = list(row.section_path)
                member_section = _section_for_path(active_path, copied_member.sections)
                if member_section is not None:
                    active_section = member_section
            elif member_index and row.role == "data" and active_path:
                row.section_path = list(active_path)
                if active_section is not None and row.row_id not in active_section.row_ids:
                    active_section.row_ids.append(row.row_id)
            aggregate.rows.append(row)


def _section_for_path(path: list[str], sections: list[TableSection]) -> TableSection | None:
    if not path:
        return None
    return next(
        (
            section
            for section in reversed(sections)
            if [*section.parent_path, section.title] == path
        ),
        None,
    )


def _continuation_role(index: int, member_count: int) -> str:
    if index == 0:
        return "head"
    if index == member_count - 1:
        return "tail"
    return "member"


def _deduplicate_reason_codes(edges: list[ContinuationCandidate]) -> list[str]:
    return list(dict.fromkeys(reason for edge in edges for reason in edge.reason_codes))


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
