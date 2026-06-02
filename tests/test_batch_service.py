from pathlib import Path

import pytest

from langparse.metrics import BatchRunResult
from langparse.services.batch_service import BatchParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


class StubParseService:
    def __init__(self):
        self.calls = []

    def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        self.calls.append((Path(file_path), engine_name, kwargs))
        return ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine=engine_name,
            pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
            markdown_content="Hello",
            metadata={},
        )

    def render_output(self, parsed, fmt):
        return parsed.markdown_content if fmt == "markdown" else "{}"


def test_batch_service_writes_outputs_and_summary(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"

    service = BatchParseService(parse_service=StubParseService())
    result = service.run([pdf], output_dir=output_dir, fmt="markdown", max_workers=1)

    assert isinstance(result, BatchRunResult)
    assert result.success_count == 1
    assert (output_dir / "a.md").read_text(encoding="utf-8") == "Hello"
    assert (output_dir / "batch-results.jsonl").exists()
    assert (output_dir / "batch-summary.json").exists()


def test_batch_service_skip_existing_marks_item_skipped(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "a.md").write_text("old", encoding="utf-8")

    parse_service = StubParseService()
    result = BatchParseService(parse_service=parse_service).run(
        [pdf],
        output_dir=output_dir,
        fmt="markdown",
        max_workers=1,
        skip_existing=True,
    )

    assert result.skipped_count == 1
    assert parse_service.calls == []


def test_batch_service_records_failure_when_fail_fast_false(tmp_path):
    class FailingParseService(StubParseService):
        def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
            raise RuntimeError("parser failed")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    result = BatchParseService(parse_service=FailingParseService()).run(
        [pdf],
        output_dir=tmp_path / "out",
        max_workers=1,
        fail_fast=False,
    )

    assert result.failed_count == 1
    assert result.items[0].error_type == "parse_failed"


def test_batch_service_raises_when_fail_fast_true(tmp_path):
    class FailingParseService(StubParseService):
        def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
            raise RuntimeError("parser failed")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError, match="parser failed"):
        BatchParseService(parse_service=FailingParseService()).run(
            [pdf],
            output_dir=tmp_path / "out",
            max_workers=1,
            fail_fast=True,
        )
