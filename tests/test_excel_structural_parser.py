from openpyxl import Workbook

from langparse.parsers.excel_parser import ExcelParser
from langparse.workbooks.types import WorkbookIR


def test_xlsx_parser_returns_structure_without_fake_pages(sample_excel_file):
    parser = ExcelParser()

    parsed = parser.parse_result(sample_excel_file)
    rendered = parser.parse(sample_excel_file)

    assert isinstance(parsed.structure, WorkbookIR)
    assert parsed.paginated is False
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.coverage_ratio == 1.0
    assert "<!-- page_number:" not in rendered.content
    assert "### Sheet: Sheet1" not in rendered.content
    assert "## Sheet: Sheet1" in rendered.content
    assert parsed.markdown_content == "\n\n".join(page.markdown_content for page in parsed.pages)


def test_xlsx_parser_does_not_emit_unnamed_headers(tmp_path):
    path = tmp_path / "cover.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Label"
    sheet["B1"] = "Title"
    workbook.save(path)

    parsed = ExcelParser().parse_result(path)

    assert "Unnamed:" not in parsed.markdown_content
    assert parsed.pages[0].tables[0]["rows"][0] == ["A", "B"]
    assert parsed.pages[0].tables[0]["rows"][1] == ["Label", "Title"]
