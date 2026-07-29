import pytest

from langparse.autoparser import AutoParser
from langparse.services import parse_service


def test_autoparser_routing(sample_md_file, sample_docx_file, sample_excel_file):
    doc = AutoParser.parse(sample_md_file)
    assert doc.metadata["filename"] == "test.md"

    doc = AutoParser.parse(sample_docx_file)
    assert doc.metadata["extension"] == ".docx"

    doc = AutoParser.parse(sample_excel_file)
    assert doc.metadata["extension"] == ".xlsx"


def test_autoparser_pdf_path_passes_engine_kwargs(tmp_path, monkeypatch):
    """Engine selection and engine kwargs must reach the constructed engine."""
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    built = {}

    class RecordingEngine:
        def __init__(self, **config):
            built.update(config)

        def process(self, file_path, **kwargs):
            return iter(())

    monkeypatch.setitem(parse_service.ENGINE_MAP, "mineru", RecordingEngine)

    AutoParser.parse(pdf_path, engine="mineru", device="cpu")

    assert built["device"] == "cpu"


def test_autoparser_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"PK")

    with pytest.raises(ValueError, match="Unsupported file extension"):
        AutoParser.parse(path)


def test_autoparser_parse_result_returns_structured_pages(sample_docx_file):
    parsed = AutoParser.parse_result(sample_docx_file)

    assert parsed.engine == "docx"
    assert parsed.pages[0].tables
