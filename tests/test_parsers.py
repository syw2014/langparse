from langparse.parsers.docx_parser import DocxParser
from langparse.parsers.excel_parser import ExcelParser
from langparse.parsers.markdown_parser import MarkdownParser


def test_markdown_parser(sample_md_file):
    parser = MarkdownParser()
    doc = parser.parse(sample_md_file)
    assert doc.metadata["filename"] == "test.md"
    assert "# Title" in doc.content
    assert "<!-- page_number: 2 -->" in doc.content


def test_docx_parser(sample_docx_file):
    parser = DocxParser()
    doc = parser.parse(sample_docx_file)

    assert doc.metadata["extension"] == ".docx"
    assert "# Test Document" in doc.content
    assert "Paragraph 1" in doc.content
    # Check table conversion
    assert "| Header1 | Header2 |" in doc.content
    assert "| Val1 | Val2 |" in doc.content
    # Check page marker injection
    assert "<!-- page_number: 1 -->" in doc.content


def test_excel_parser(sample_excel_file):
    parser = ExcelParser()
    doc = parser.parse(sample_excel_file)

    assert doc.metadata["extension"] == ".xlsx"
    # Check sheet headers
    assert "### Sheet: Sheet1" in doc.content
    assert "### Sheet: Sheet2" in doc.content
    # Check page markers
    assert "<!-- page_number: 1 -->" in doc.content
    assert "<!-- page_number: 2 -->" in doc.content
    # Check data
    # Remove whitespace for comparison to avoid alignment issues
    clean_content = doc.content.replace(" ", "")
    assert "|1|3|" in clean_content
