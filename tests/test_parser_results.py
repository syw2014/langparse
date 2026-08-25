"""Every parser must produce the structured ParsedDocumentResult, not just a
markdown blob, so metrics/quality/batch work for more than PDFs."""

from pathlib import Path

from langparse.core.rendering import document_from_result
from langparse.metrics import collect_parse_metrics
from langparse.parsers.docx_parser import DocxParser
from langparse.parsers.excel_parser import ExcelParser
from langparse.parsers.markdown_parser import MarkdownParser
from langparse.types import ParsedDocumentResult


def test_markdown_parse_result_is_a_single_unpaginated_page(sample_md_file):
    parsed = MarkdownParser().parse_result(sample_md_file)

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.paginated is False
    assert len(parsed.pages) == 1
    assert parsed.pages[0].markdown_content == sample_md_file.read_text(encoding="utf-8")


def test_markdown_document_round_trip_is_byte_identical(tmp_path):
    source = tmp_path / "doc.md"
    original = "# Title\n\nBody text\n\n## Section\n\nMore text\n"
    source.write_text(original, encoding="utf-8")

    assert MarkdownParser().parse(source).content == original


def test_docx_parse_result_exposes_structured_tables(sample_docx_file):
    parsed = DocxParser().parse_result(sample_docx_file)

    assert len(parsed.pages) == 1
    tables = parsed.pages[0].tables
    assert len(tables) == 1
    assert tables[0]["rows"] == [["Header1", "Header2"], ["Val1", "Val2"]]


def test_docx_parse_result_records_element_kinds(sample_docx_file):
    parsed = DocxParser().parse_result(sample_docx_file)

    kinds = [element.kind for element in parsed.pages[0].elements]
    assert "heading" in kinds
    assert "table" in kinds


def test_excel_parse_result_exposes_one_non_paginated_part_per_sheet(sample_excel_file):
    parsed = ExcelParser().parse_result(sample_excel_file)

    assert parsed.paginated is False
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert all(page.metadata["part_kind"] == "sheet" for page in parsed.pages)
    assert all(page.tables for page in parsed.pages)


def test_metrics_now_count_tables_for_office_formats(sample_docx_file):
    parsed = DocxParser().parse_result(sample_docx_file)

    metrics = collect_parse_metrics(parsed, 1.0)

    assert metrics.table_count == 1
    assert metrics.page_count == 1


def test_parse_result_carries_source_identity(sample_docx_file):
    parsed = DocxParser().parse_result(sample_docx_file)

    assert parsed.filename == "test.docx"
    assert Path(parsed.source) == Path(sample_docx_file)
    assert parsed.metadata["extension"] == ".docx"


def test_csv_page_has_no_sheet_heading(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("A,B\n1,2\n", encoding="utf-8")

    parsed = ExcelParser().parse_result(source)

    assert len(parsed.pages) == 1
    assert "### Sheet:" not in parsed.pages[0].markdown_content


def test_blank_cells_do_not_become_the_string_nan(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("A,B\n1,\n", encoding="utf-8")

    rows = ExcelParser().parse_result(source).pages[0].tables[0]["rows"]

    assert rows == [["A", "B"], ["1", ""]]


def test_document_metadata_does_not_alias_the_parse_result(sample_docx_file):
    parser = DocxParser()
    parsed = parser.parse_result(sample_docx_file)
    document = document_from_result(parsed)

    parsed.metadata["extension"] = ".mutated"

    assert document.metadata["parsed_metadata"]["extension"] == ".docx"
