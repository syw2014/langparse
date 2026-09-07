from __future__ import annotations

import re

from openpyxl.utils import get_column_letter, range_boundaries

from langparse.workbooks.labels import is_section_label, is_total_label
from langparse.workbooks.types import (
    CandidateRegion,
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    SheetSnapshot,
    SourceRef,
    TableFragment,
    TableSection,
    stable_id,
)

PAGE_RE = re.compile(r"第\s*(\d+)\s*页\s*共\s*(\d+)\s*页")
ROW_NUMBER_RE = re.compile(r"[1-9]\d*(?:\.\d+)*")
CONTEXT_LABEL_RE = re.compile(
    r"^(?:工程名称|单位工程名称|项目名称|编制单位|编制日期|建设单位|单位|币种)\s*[:：]\s*\S"
)


def interpret_logical_table(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
) -> LogicalTable:
    """Interpret deterministic print fragments and their shared header."""

    min_col, min_row, max_col, max_row = range_boundaries(candidate.source_ref.range)
    page_markers = _page_markers(sheet, min_row, max_row, min_col, max_col)
    fragments = _build_fragments(
        sheet,
        candidate,
        page_markers,
        min_col,
        min_row,
        max_col,
        max_row,
    )
    header_rows = fragments[0].header_row_numbers if fragments else []
    columns = _build_header_columns(
        sheet,
        candidate.source_ref,
        header_rows,
        min_col,
        max_col,
    )
    title_rows = fragments[0].title_row_numbers if fragments else []
    title = _first_text(sheet, title_rows[0], min_col, max_col) if title_rows else ""
    context = [
        text
        for row_number in fragments[0].context_row_numbers
        for text in [_row_text(sheet, row_number, min_col, max_col)]
        if text
    ]
    rows, sections = _build_rows_and_sections(
        sheet,
        candidate,
        fragments,
        min_col,
        min_row,
        max_col,
        max_row,
    )
    return LogicalTable(
        table_id=stable_id("table", candidate.source_ref.key),
        title=title,
        context=context,
        columns=columns,
        rows=rows,
        fragments=fragments,
        sections=sections,
        source_refs=[candidate.source_ref],
    )


def _build_rows_and_sections(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
    fragments: list[TableFragment],
    min_col: int,
    min_row: int,
    max_col: int,
    max_row: int,
) -> tuple[list[LogicalRow], list[TableSection]]:
    roles: dict[int, str] = {}
    for fragment_index, fragment in enumerate(fragments):
        for row_number in fragment.title_row_numbers:
            roles[row_number] = "title" if fragment_index == 0 else "repeated_title"
        for row_number in fragment.context_row_numbers:
            roles[row_number] = "context" if fragment_index == 0 else "repeated_context"
        for row_number in fragment.header_row_numbers:
            roles[row_number] = "header" if fragment_index == 0 else "repeated_header"

    header_rows = fragments[0].header_row_numbers if fragments else []
    ordinal_column = any(
        _cell_text(sheet, row, min_col).strip() in {"序号", "编号"} for row in header_rows
    )
    logical_rows: list[LogicalRow] = []
    sections: list[TableSection] = []
    current_section: TableSection | None = None
    for row_number in range(min_row, max_row + 1):
        values = [
            _raw_cell_text(sheet, row_number, column) for column in range(min_col, max_col + 1)
        ]
        first_cell = sheet.cells.get(f"{get_column_letter(min_col)}{row_number}")
        role = roles.get(row_number) or _classify_content_row(
            values,
            merged_section=bool(first_cell and first_cell.colspan > 1),
            ordinal_column=ordinal_column,
        )
        row_range = (
            f"{get_column_letter(min_col)}{row_number}:{get_column_letter(max_col)}{row_number}"
        )
        source_ref = SourceRef(sheet_name=sheet.name, range=row_range)
        row_id = stable_id("row", candidate.source_ref.key, str(row_number))
        if role == "section_header":
            title = _section_title(values)
            current_section = TableSection(
                section_id=stable_id("section", candidate.source_ref.key, str(row_number), title),
                title=title,
                source_ref=source_ref,
            )
            sections.append(current_section)
        section_path = [current_section.title] if current_section is not None else []
        source_cells = [
            f"{get_column_letter(column)}{row_number}"
            for column in range(min_col, max_col + 1)
            if f"{get_column_letter(column)}{row_number}" in sheet.cells
        ]
        logical_row = LogicalRow(
            row_id=row_id,
            source_ref=source_ref,
            role=role,
            values=values,
            source_cells=source_cells,
            section_path=section_path,
            metadata={"row_number": row_number},
        )
        logical_rows.append(logical_row)
        if current_section is not None and role in {"data", "total"}:
            current_section.row_ids.append(row_id)
    return logical_rows, sections


def _classify_content_row(
    values: list[str], *, merged_section: bool = False, ordinal_column: bool = False
) -> str:
    nonempty = [value.strip() for value in values if value.strip()]
    first = values[0].strip() if values else ""
    # A total is identified by its leading label, never by a word embedded in
    # arbitrary description columns. A numbered record remains a record.
    if nonempty and is_total_label(nonempty[0]):
        return "total"
    if merged_section and is_section_label(first):
        return "section_header"
    # Printed budget sections use empty/zero code columns followed by a title
    # and amounts. A blank merged product cell plus an item/unit is a detail.
    if ordinal_column and first in {"", "0"}:
        if _section_title(values) and any(
            _is_number(value) and float(value) != 0 for value in values[3:]
        ):
            return "section_header"
    if ROW_NUMBER_RE.fullmatch(first):
        return "data"
    if ordinal_column:
        # Preserve non-record annotations such as “其中” in numbered schedules.
        return "data" if len(values) > 1 and any(c.isdigit() for c in values[1]) else "unknown"
    if len(nonempty) >= 2:
        return "data"
    return "unknown"


def _section_title(values: list[str]) -> str:
    if values and is_section_label(values[0]):
        return values[0].strip()
    for value in values[1:6]:
        text = value.strip()
        if text and not _is_number(text):
            return text
    return ""


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _page_markers(
    sheet: SheetSnapshot,
    min_row: int,
    max_row: int,
    min_col: int,
    max_col: int,
) -> list[tuple[int, int, int]]:
    markers = []
    for row_number in range(min_row, max_row + 1):
        match = PAGE_RE.search(_row_text(sheet, row_number, min_col, max_col))
        if match:
            markers.append((row_number, int(match.group(1)), int(match.group(2))))
    return markers


def _build_fragments(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
    page_markers: list[tuple[int, int, int]],
    min_col: int,
    min_row: int,
    max_col: int,
    max_row: int,
) -> list[TableFragment]:
    if len(page_markers) == 1:
        context_row, page_number, total_pages = page_markers[0]
        title_rows, context_rows = _print_preamble(sheet, min_row, context_row, min_col, max_col)
        header_rows = _header_rows_after(
            sheet, context_row, context_row + 1, max_row, min_col, max_col
        )
        return [
            TableFragment(
                fragment_id=stable_id("fragment", candidate.source_ref.key, str(page_number)),
                source_ref=candidate.source_ref,
                page_number=page_number,
                total_pages=total_pages,
                title_row_numbers=title_rows,
                context_row_numbers=context_rows,
                header_row_numbers=header_rows,
                diagnostics=[{"reason_code": "single_print_fragment"}],
            )
        ]

    if not _valid_page_sequence(page_markers):
        title_rows, context_rows = (
            ([], [])
            if "native_table_anchor" in candidate.reason_codes
            else _unpaged_preamble(sheet, min_row, max_row, min_col, max_col)
        )
        header_start = context_rows[-1] + 1 if context_rows else min_row
        header_rows = _header_rows_after(
            sheet, header_start - 1, header_start, max_row, min_col, max_col
        )
        return [
            TableFragment(
                fragment_id=stable_id("fragment", candidate.source_ref.key),
                source_ref=candidate.source_ref,
                title_row_numbers=title_rows,
                context_row_numbers=context_rows,
                header_row_numbers=header_rows,
                diagnostics=[{"reason_code": "no_consistent_print_sequence"}],
            )
        ]

    starts = [max(min_row, row_number - 1) for row_number, _, _ in page_markers]
    fragments: list[TableFragment] = []
    header_fingerprints: list[tuple[tuple[str, ...], ...]] = []
    for index, ((context_row, page_number, total_pages), start_row) in enumerate(
        zip(page_markers, starts, strict=True)
    ):
        end_row = starts[index + 1] - 1 if index + 1 < len(starts) else max_row
        header_rows = _header_rows_after(
            sheet,
            context_row,
            start_row,
            end_row,
            min_col,
            max_col,
        )
        header_fingerprints.append(
            tuple(
                tuple(
                    _cell_text(sheet, row_number, column) for column in range(min_col, max_col + 1)
                )
                for row_number in header_rows
            )
        )
        source_range = (
            f"{get_column_letter(min_col)}{start_row}:{get_column_letter(max_col)}{end_row}"
        )
        fragments.append(
            TableFragment(
                fragment_id=stable_id("fragment", candidate.source_ref.key, str(page_number)),
                source_ref=SourceRef(sheet_name=sheet.name, range=source_range),
                page_number=page_number,
                total_pages=total_pages,
                title_row_numbers=[start_row] if start_row < context_row else [],
                context_row_numbers=[context_row],
                header_row_numbers=header_rows,
            )
        )

    if len(set(header_fingerprints)) != 1:
        diagnostic = {"reason_code": "header_fingerprint_mismatch"}
        for fragment in fragments:
            fragment.confidence = 0.5
            fragment.diagnostics.append(diagnostic)
    return fragments


def _valid_page_sequence(markers: list[tuple[int, int, int]]) -> bool:
    if len(markers) < 2:
        return False
    pages = [page for _, page, _ in markers]
    totals = {total for _, _, total in markers}
    return len(totals) == 1 and pages == list(range(pages[0], pages[0] + len(pages)))


def _is_context_row(sheet: SheetSnapshot, row: int, min_col: int, max_col: int) -> bool:
    values = [
        text.strip()
        for column in range(min_col, max_col + 1)
        if (text := _raw_cell_text(sheet, row, column)).strip()
    ]
    return bool(values) and all(
        CONTEXT_LABEL_RE.match(value) or PAGE_RE.search(value) for value in values
    )


def _print_preamble(
    sheet: SheetSnapshot, start: int, marker_row: int, min_col: int, max_col: int
) -> tuple[list[int], list[int]]:
    # A page marker anchors the preamble; keep preceding labelled context as well.
    contexts = [marker_row]
    for row in range(marker_row - 1, start - 1, -1):
        if not _is_context_row(sheet, row, min_col, max_col):
            break
        contexts.insert(0, row)
    titles = [start] if start < contexts[0] else []
    return titles, contexts


def _unpaged_preamble(
    sheet: SheetSnapshot, start: int, end: int, min_col: int, max_col: int
) -> tuple[list[int], list[int]]:
    # A sparse title alone is ambiguous with a merged parent header. Require
    # explicit labelled context immediately afterwards before assigning ownership.
    first_values = [
        _raw_cell_text(sheet, start, column).strip() for column in range(min_col, max_col + 1)
    ]
    title = (
        not _is_context_row(sheet, start, min_col, max_col)
        and sum(bool(value) for value in first_values) == 1
    )
    context_start = start + 1 if title else start
    contexts = []
    for row in range(context_start, end + 1):
        if not _is_context_row(sheet, row, min_col, max_col):
            break
        contexts.append(row)
    if not contexts or contexts[-1] == end:
        return [], []
    return [start] if title else [], contexts


def _header_rows_after(
    sheet: SheetSnapshot,
    context_row: int,
    start_row: int,
    end_row: int,
    min_col: int,
    max_col: int,
) -> list[int]:
    rows = []
    for row_number in range(max(start_row, context_row + 1), end_row + 1):
        if _looks_like_data_or_section(sheet, row_number, min_col, max_col):
            break
        if rows and _flat_header(sheet, rows[-1], min_col, max_col):
            # A complete flat schema also supports text-only records. Do not
            # consume the entire body while waiting for a numeric identifier.
            break
        if _row_text(sheet, row_number, min_col, max_col):
            rows.append(row_number)
    return rows


def _flat_header(sheet: SheetSnapshot, row: int, min_col: int, max_col: int) -> bool:
    cells = [
        sheet.cells.get(f"{get_column_letter(col)}{row}") for col in range(min_col, max_col + 1)
    ]
    return len(cells) >= 2 and all(
        cell is not None
        and cell.display_value.strip()
        and not cell.merge_anchor
        and cell.colspan == 1
        and cell.rowspan == 1
        for cell in cells
    )


def _looks_like_data_or_section(
    sheet: SheetSnapshot,
    row_number: int,
    min_col: int,
    max_col: int,
) -> bool:
    first = _cell_text(sheet, row_number, min_col).strip()
    if re.fullmatch(r"\d+", first) or ROW_NUMBER_RE.fullmatch(first):
        return True
    values = [_raw_cell_text(sheet, row_number, column) for column in range(min_col, max_col + 1)]
    if any(_is_number(value) for value in values) and any(
        value.strip() and not _is_number(value) for value in values
    ):
        return True
    first_cell = sheet.cells.get(f"{get_column_letter(min_col)}{row_number}")
    return is_total_label(first) or bool(
        first_cell and first_cell.colspan > 1 and is_section_label(first)
    )


def _build_header_columns(
    sheet: SheetSnapshot,
    candidate_ref: SourceRef,
    header_rows: list[int],
    min_col: int,
    max_col: int,
) -> list[HeaderColumn]:
    columns = []
    for column in range(min_col, max_col + 1):
        coordinate = get_column_letter(column)
        path = []
        source_refs = []
        for row_number in header_rows:
            text = _cell_text(sheet, row_number, column).strip()
            if text and (not path or path[-1] != text):
                path.append(text)
            source_refs.append(SourceRef(sheet_name=sheet.name, range=f"{coordinate}{row_number}"))
        columns.append(
            HeaderColumn(
                column_id=stable_id("column", candidate_ref.key, coordinate),
                coordinate=coordinate,
                path=path,
                source_refs=source_refs,
            )
        )
    return columns


def _cell_text(sheet: SheetSnapshot, row_number: int, column: int) -> str:
    coordinate = f"{get_column_letter(column)}{row_number}"
    cell = sheet.cells.get(coordinate)
    if cell is None:
        return ""
    if cell.merge_anchor:
        anchor = sheet.cells.get(cell.merge_anchor)
        return anchor.display_value if anchor is not None else ""
    return cell.display_value


def _raw_cell_text(sheet: SheetSnapshot, row_number: int, column: int) -> str:
    coordinate = f"{get_column_letter(column)}{row_number}"
    cell = sheet.cells.get(coordinate)
    if cell is None or cell.merge_anchor is not None:
        return ""
    return cell.display_value


def _row_text(sheet: SheetSnapshot, row_number: int, min_col: int, max_col: int) -> str:
    return " | ".join(
        text
        for column in range(min_col, max_col + 1)
        for text in [_cell_text(sheet, row_number, column).strip()]
        if text
    )


def _first_text(sheet: SheetSnapshot, row_number: int, min_col: int, max_col: int) -> str:
    for column in range(min_col, max_col + 1):
        text = _cell_text(sheet, row_number, column).strip()
        if text:
            return text
    return ""
