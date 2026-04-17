from types import SimpleNamespace

import pytest

from langparse.core.engine import PageResult
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


def test_parse_file_uses_process_document_fast_path(tmp_path):
    class FastPathEngine:
        def __init__(self):
            self.process_called = False

        def process_document(self, file_path, **kwargs):
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
                markdown_content="Hello",
                metadata={"mode": "fast"},
            )

        def process(self, file_path, **kwargs):
            self.process_called = True
            raise AssertionError("process() should not be used when process_document exists")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")

    service = ParseService()
    result = service.parse_file(pdf, engine_name="simple", engine=FastPathEngine())

    assert result.metadata["engine"] == "simple"
    assert result.metadata["parsed_metadata"] == {"mode": "fast"}
    assert "Hello" in result.content


def test_parse_file_falls_back_to_process_when_process_document_missing(tmp_path):
    class LegacyEngine:
        def process(self, file_path, **kwargs):
            return iter(
                [
                    PageResult(page_number=1, markdown_content="Page 1"),
                    PageResult(page_number=2, markdown_content="Page 2"),
                ]
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")

    service = ParseService()
    result = service.parse_file(pdf, engine_name="simple", engine=LegacyEngine())

    assert result.metadata["engine"] == "simple"
    assert "<!-- page_number: 1 -->" in result.content
    assert "Page 1" in result.content
    assert "<!-- page_number: 2 -->" in result.content
    assert "Page 2" in result.content


def test_parse_file_rejects_invalid_process_document_shape(tmp_path):
    class InvalidFastPathEngine:
        def process_document(self, file_path, **kwargs):
            return [SimpleNamespace(page_number=1, markdown_content="bad")]

        def process(self, file_path, **kwargs):
            raise AssertionError("process() should not be used after invalid process_document output")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")

    service = ParseService()

    with pytest.raises(TypeError, match="process_document must return ParsedDocumentResult"):
        service.parse_file(pdf, engine_name="simple", engine=InvalidFastPathEngine())


def test_expand_inputs_supports_directory_and_list(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_text("x")
    b.write_text("y")
    service = ParseService()

    inputs = service.expand_inputs([str(tmp_path)])

    assert str(a) in [str(p) for p in inputs]
    assert str(b) in [str(p) for p in inputs]
