from __future__ import annotations

from openpyxl.utils import get_column_letter, range_boundaries

from langparse.types import ParsedElement, ParsedPageResult
from langparse.workbooks.types import (
    FormBlock,
    LogicalRow,
    LogicalTable,
    MatrixBlock,
    SheetIR,
    SheetSnapshot,
    TextBlock,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
)


def render_workbook_markdown(snapshot: WorkbookSnapshot, ir: WorkbookIR) -> str:
    """Render semantic logical tables while retaining source coordinates."""

    ir_by_index = {sheet.index: sheet for sheet in ir.sheets}
    sections = [
        _render_sheet_markdown(sheet, ir_by_index.get(sheet.index)) for sheet in snapshot.sheets
    ]
    return "\n\n".join(sections)


def compatibility_pages(
    snapshot: WorkbookSnapshot,
    ir: WorkbookIR,
) -> list[ParsedPageResult]:
    """Provide stable one-sheet compatibility parts for existing consumers."""

    ir_by_index = {sheet.index: sheet for sheet in ir.sheets}
    pages: list[ParsedPageResult] = []
    for sheet in snapshot.sheets:
        sheet_ir = ir_by_index.get(sheet.index)
        source_range = _source_range(sheet, sheet_ir)
        markdown = _render_sheet_markdown(sheet, sheet_ir)
        metadata = {
            "part_kind": "sheet",
            "sheet_name": sheet.name,
            "source_range": source_range,
        }
        tables = []
        elements = []
        if source_range is not None:
            columns, row_numbers, data_rows = _sheet_grid(sheet, source_range)
            table = {
                "rows": [columns, *data_rows],
                "columns": columns,
                "row_numbers": row_numbers,
                "sheet_name": sheet.name,
                "source_range": source_range,
            }
            tables.append(table)
            elements.append(
                ParsedElement(
                    kind="table",
                    text=_render_grid(columns, data_rows),
                    metadata={"source_range": source_range},
                )
            )
        pages.append(
            ParsedPageResult(
                page_number=sheet.index + 1,
                markdown_content=markdown,
                plain_text=markdown,
                elements=elements,
                tables=tables,
                metadata=metadata,
            )
        )
    return pages


def _render_sheet_markdown(sheet: SheetSnapshot, sheet_ir: SheetIR | None) -> str:
    heading = f"## Sheet: {sheet.name}"
    source_range = _source_range(sheet, sheet_ir)
    if source_range is None:
        return f"{heading}\n\n_Empty sheet._"
    if sheet_ir is not None and sheet_ir.blocks:
        rendered = [_render_block(sheet, block) for block in sheet_ir.blocks]
        return "\n\n".join([heading, *rendered])
    columns, _, data_rows = _sheet_grid(sheet, source_range)
    source_comment = f"<!-- source_range: {sheet.name}!{source_range} -->"
    return f"{heading}\n\n{source_comment}\n\n{_render_grid(columns, data_rows)}"


def _render_block(sheet: SheetSnapshot, block: WorkbookBlock) -> str:
    if block.logical_table is not None:
        return _render_logical_table(block.logical_table)
    if block.form is not None:
        return _render_form(block.form)
    if block.matrix is not None:
        return _render_matrix(block.matrix)
    if block.text is not None:
        return _render_text(block.text)
    source_range = block.source_refs[0].range
    columns, _, rows = _sheet_grid(sheet, source_range)
    source_comment = f"<!-- source_range: {sheet.name}!{source_range} -->"
    return f"{source_comment}\n\n{_render_grid(columns, rows)}"


def _render_logical_table(table: LogicalTable) -> str:
    source_ranges = ", ".join(source_ref.key for source_ref in table.source_refs)
    parts = [f"<!-- source_ranges: {source_ranges} -->"]
    if table.continuation_id is not None:
        parts.append(
            f"<!-- continuation_id: {table.continuation_id}; role: {table.continuation_role} -->"
        )
    if table.title:
        parts.append(f"### Table: {table.title}")
    if table.context:
        parts.append("\n".join(f"> {line}" for line in table.context))

    columns = [" / ".join(column.path) or column.coordinate for column in table.columns]
    eligible_rows = [row for row in table.rows if row.role in {"data", "total", "unknown"}]
    groups = _group_rows_by_section(eligible_rows)
    for section_path, rows in groups:
        if section_path:
            parts.append(f"#### Section: {' / '.join(section_path)}")
        parts.append(_render_grid(columns, [row.values for row in rows]))
    if not groups:
        parts.append("_No semantic data rows._")
    return "\n\n".join(parts)


def _render_form(form: FormBlock) -> str:
    source_ranges = ", ".join(source_ref.key for source_ref in form.source_refs)
    parts = [f"<!-- source_ranges: {source_ranges} -->"]
    if form.title:
        parts.append(f"### Form: {form.title}")
    if form.fields:
        parts.append(
            _render_grid(["Field", "Value"], [[field.label, field.value] for field in form.fields])
        )
    parts.extend(line.text for line in form.free_text)
    return "\n\n".join(parts)


def _render_matrix(matrix: MatrixBlock) -> str:
    source_ranges = ", ".join(source_ref.key for source_ref in matrix.source_refs)
    parts = [f"<!-- source_ranges: {source_ranges} -->"]
    if matrix.title:
        parts.append(f"### Matrix: {matrix.title}")
    columns = ["", *[header.value for header in matrix.column_headers]]
    rows = [
        [header.value, *values]
        for header, values in zip(matrix.row_headers, matrix.values, strict=True)
    ]
    parts.append(_render_grid(columns, rows))
    return "\n\n".join(parts)


def _render_text(text: TextBlock) -> str:
    source_ranges = ", ".join(source_ref.key for source_ref in text.source_refs)
    return "\n\n".join(
        [f"<!-- source_ranges: {source_ranges} -->", *[line.text for line in text.lines]]
    )


def _group_rows_by_section(rows: list[LogicalRow]) -> list[tuple[list[str], list[LogicalRow]]]:
    groups: list[tuple[list[str], list[LogicalRow]]] = []
    for row in rows:
        if not groups or groups[-1][0] != row.section_path:
            groups.append((list(row.section_path), []))
        groups[-1][1].append(row)
    return groups


def _source_range(sheet: SheetSnapshot, sheet_ir: SheetIR | None) -> str | None:
    if sheet.used_range is not None:
        return sheet.used_range
    if sheet_ir is not None and sheet_ir.blocks and sheet_ir.blocks[0].source_refs:
        return sheet_ir.blocks[0].source_refs[0].range
    return None


def _sheet_grid(
    sheet: SheetSnapshot,
    source_range: str,
) -> tuple[list[str], list[int], list[list[str]]]:
    min_col, min_row, max_col, max_row = range_boundaries(source_range)
    columns = [get_column_letter(column) for column in range(min_col, max_col + 1)]
    row_numbers = list(range(min_row, max_row + 1))
    rows: list[list[str]] = []
    for row_number in row_numbers:
        row: list[str] = []
        for column in columns:
            cell = sheet.cells.get(f"{column}{row_number}")
            if cell is None or cell.merge_anchor is not None:
                row.append("")
            else:
                row.append(cell.display_value)
        rows.append(row)
    return columns, row_numbers, rows


def _render_grid(columns: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(_escape_markdown(value) for value in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_escape_markdown(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def _escape_markdown(value: str) -> str:
    return (
        str(value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("|", r"\|")
        .replace("\n", "<br>")
    )
