from __future__ import annotations

from collections.abc import Callable

from openpyxl.utils import range_boundaries

from langparse.core.rendering import document_metadata
from langparse.types import Chunk, ParsedDocumentResult
from langparse.workbooks.types import WorkbookIR


class WorkbookStructuralChunker:
    """Pack complete raw-grid rows directly from workbook compatibility facts."""

    def __init__(
        self,
        max_chunk_size: int = 1000,
        length_function: Callable[[str], int] = len,
    ):
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be positive")
        self.max_chunk_size = max_chunk_size
        self.length_function = length_function

    def chunk(self, parsed: ParsedDocumentResult) -> list[Chunk]:
        if not isinstance(parsed.structure, WorkbookIR):
            raise TypeError("WorkbookStructuralChunker requires WorkbookIR structure")

        ir_sheets = {sheet.index: sheet for sheet in parsed.structure.sheets}
        chunks: list[Chunk] = []
        for page in parsed.pages:
            sheet_name = page.metadata.get("sheet_name")
            sheet_ir = ir_sheets.get(page.page_number - 1)
            confidence = (
                sheet_ir.blocks[0].confidence if sheet_ir is not None and sheet_ir.blocks else 1.0
            )
            for table in page.tables:
                rows = table.get("rows", [])
                if not rows:
                    continue
                columns = [str(value) for value in table.get("columns") or rows[0]]
                data_rows = [[str(value) for value in row] for row in rows[1:]]
                row_numbers = list(table.get("row_numbers", []))
                if len(row_numbers) != len(data_rows):
                    row_numbers = _row_numbers(table.get("source_range"), len(data_rows))
                chunks.extend(
                    self._pack_table(
                        parsed=parsed,
                        sheet_name=str(sheet_name),
                        sheet_ordinal=page.page_number,
                        columns=columns,
                        rows=data_rows,
                        row_numbers=row_numbers,
                        confidence=confidence,
                        chunk_index_offset=len(chunks),
                    )
                )
        return chunks

    def _pack_table(
        self,
        *,
        parsed: ParsedDocumentResult,
        sheet_name: str,
        sheet_ordinal: int,
        columns: list[str],
        rows: list[list[str]],
        row_numbers: list[int],
        confidence: float,
        chunk_index_offset: int,
    ) -> list[Chunk]:
        packed: list[Chunk] = []
        pending_rows: list[list[str]] = []
        pending_numbers: list[int] = []

        def emit(*, oversized: bool = False) -> None:
            if not pending_rows:
                return
            source_range = _source_range(sheet_name, columns, pending_numbers)
            content = _render_chunk(sheet_name, source_range, columns, pending_rows)
            metadata = document_metadata(parsed)
            metadata.update(
                {
                    "chunk_type": "raw_grid_rows",
                    "chunk_index": chunk_index_offset + len(packed),
                    "sheet_name": sheet_name,
                    "sheet_ordinal": sheet_ordinal,
                    "source_ranges": [source_range],
                    "row_numbers": list(pending_numbers),
                    "confidence": confidence,
                    "warnings": list(parsed.diagnostics.warnings)
                    if parsed.diagnostics is not None
                    else [],
                }
            )
            if oversized:
                metadata["oversized"] = True
            packed.append(
                Chunk(
                    content=content,
                    metadata=metadata,
                    structured_payload={
                        "columns": list(columns),
                        "rows": [list(row) for row in pending_rows],
                    },
                )
            )
            pending_rows.clear()
            pending_numbers.clear()

        for row, row_number in zip(rows, row_numbers, strict=True):
            candidate_rows = [*pending_rows, row]
            candidate_numbers = [*pending_numbers, row_number]
            candidate_range = _source_range(sheet_name, columns, candidate_numbers)
            candidate = _render_chunk(sheet_name, candidate_range, columns, candidate_rows)
            if pending_rows and self.length_function(candidate) > self.max_chunk_size:
                emit()
                candidate_rows = [row]
                candidate_numbers = [row_number]
                candidate_range = _source_range(sheet_name, columns, candidate_numbers)
                candidate = _render_chunk(sheet_name, candidate_range, columns, candidate_rows)

            pending_rows.append(row)
            pending_numbers.append(row_number)
            if self.length_function(candidate) > self.max_chunk_size:
                emit(oversized=True)

        emit()
        return packed


def _row_numbers(source_range: str | None, count: int) -> list[int]:
    if not source_range:
        return list(range(1, count + 1))
    _, min_row, _, _ = range_boundaries(source_range)
    return list(range(min_row, min_row + count))


def _source_range(sheet_name: str, columns: list[str], row_numbers: list[int]) -> str:
    first_row = min(row_numbers)
    last_row = max(row_numbers)
    return f"{sheet_name}!{columns[0]}{first_row}:{columns[-1]}{last_row}"


def _render_chunk(
    sheet_name: str,
    source_range: str,
    columns: list[str],
    rows: list[list[str]],
) -> str:
    heading = f"## Sheet: {sheet_name}"
    source_comment = f"<!-- source_range: {source_range} -->"
    header = _markdown_row(columns)
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [_markdown_row(row) for row in rows]
    return "\n\n".join((heading, source_comment, "\n".join((header, separator, *body))))


def _markdown_row(row: list[str]) -> str:
    escaped = [
        value.replace("\r\n", "\n").replace("\r", "\n").replace("|", r"\|").replace("\n", "<br>")
        for value in row
    ]
    return "| " + " | ".join(escaped) + " |"
