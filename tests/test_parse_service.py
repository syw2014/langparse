from types import SimpleNamespace

import pytest

from langparse.core.engine import PageResult
from langparse.metrics import collect_parse_metrics
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


def test_parse_result_returns_normalized_result(tmp_path):
    class FastPathEngine:
        def process_document(self, file_path, **kwargs):
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
                markdown_content="Hello",
                metadata={},
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    parsed = ParseService().parse_result(pdf, engine_name="simple", engine=FastPathEngine())

    assert parsed.engine == "simple"
    assert parsed.pages[0].markdown_content == "Hello"


def test_collect_parse_metrics_counts_pages_tables_and_output_size():
    parsed = ParsedDocumentResult(
        source="sample.pdf",
        filename="sample.pdf",
        engine="simple",
        pages=[
            ParsedPageResult(
                page_number=1,
                markdown_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
                tables=[{"rows": [["A", "B"], ["1", "2"]]}],
                images=[{"bbox": [0, 0, 10, 10]}],
            )
        ],
        markdown_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
        metadata={"ocr_applied": True, "ocr_text_chars": 12},
    )

    metrics = collect_parse_metrics(parsed, elapsed_seconds=2)

    assert metrics.page_count == 1
    assert metrics.pages_per_second == 0.5
    assert metrics.table_count == 1
    assert metrics.image_count == 1
    assert metrics.ocr_applied is True
    assert metrics.ocr_text_chars == 12
