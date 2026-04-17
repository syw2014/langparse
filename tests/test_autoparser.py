from unittest.mock import patch

from langparse.autoparser import AutoParser


def test_autoparser_routing(sample_md_file, sample_docx_file, sample_excel_file):
    doc = AutoParser.parse(sample_md_file)
    assert doc.metadata["filename"] == "test.md"

    doc = AutoParser.parse(sample_docx_file)
    assert doc.metadata["extension"] == ".docx"

    doc = AutoParser.parse(sample_excel_file)
    assert doc.metadata["extension"] == ".xlsx"


def test_autoparser_pdf_path_passes_engine_kwargs(tmp_path):
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with patch("langparse.parsers.pdf_parser.PDFParser.__init__", return_value=None), patch(
        "langparse.parsers.pdf_parser.PDFParser.parse"
    ) as mock_parse:
        AutoParser.parse(pdf_path, engine="mineru", device="cpu")

    mock_parse.assert_called_once()
