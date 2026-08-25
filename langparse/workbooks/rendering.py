from __future__ import annotations

from openpyxl.utils import get_column_letter, range_boundaries

from langparse.types import ParsedElement, ParsedPageResult
from langparse.workbooks.types import SheetIR, SheetSnapshot, WorkbookIR, WorkbookSnapshot


def render_workbook_markdown(snapshot: WorkbookSnapshot, ir: WorkbookIR) -> str:
    """Render a coordinate-preserving workbook view without inferring headers."""

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
    columns, _, data_rows = _sheet_grid(sheet, source_range)
    source_comment = f"<!-- source_range: {sheet.name}!{source_range} -->"
    return f"{heading}\n\n{source_comment}\n\n{_render_grid(columns, data_rows)}"


def _source_range(sheet: SheetSnapshot, sheet_ir: SheetIR | None) -> str | None:
    if sheet_ir is not None and sheet_ir.blocks and sheet_ir.blocks[0].source_refs:
        return sheet_ir.blocks[0].source_refs[0].range
    return sheet.used_range


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
