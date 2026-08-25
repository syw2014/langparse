from langparse.chunkers.workbook import WorkbookStructuralChunker
from langparse.parsers.excel_parser import ExcelParser


def test_workbook_chunker_emits_source_aware_chunks(sample_excel_file):
    parsed = ExcelParser().parse_result(sample_excel_file)

    chunks = WorkbookStructuralChunker(max_chunk_size=120).chunk(parsed)

    assert chunks
    assert chunks[0].metadata["chunk_type"] == "raw_grid_rows"
    assert chunks[0].metadata["sheet_name"] == "Sheet1"
    assert chunks[0].metadata["source_ranges"]
    assert chunks[0].metadata["row_numbers"]
    assert chunks[0].structured_payload["columns"] == ["A", "B"]
    assert chunks[0].structured_payload["rows"]
    assert "| A | B |" in chunks[0].content


def test_workbook_chunker_never_splits_an_oversized_source_row(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "wide.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "x" * 200
    workbook.save(path)
    parsed = ExcelParser().parse_result(path)

    chunks = WorkbookStructuralChunker(max_chunk_size=40).chunk(parsed)

    assert len(chunks) == 1
    assert chunks[0].metadata["oversized"] is True
    assert chunks[0].structured_payload["rows"] == [["x" * 200]]
    assert chunks[0].metadata["row_numbers"] == [1]


def test_parse_result_chunk_true_populates_result(sample_excel_file):
    from langparse.services.parse_service import ParseService

    parsed = ParseService().parse_result(sample_excel_file, chunk=True)

    assert parsed.chunks
    assert parsed.chunks[0].metadata["chunk_type"] == "raw_grid_rows"
