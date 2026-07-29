from pathlib import Path

import pytest

from langparse.metrics import BatchRunResult
from langparse.services.batch_service import BatchParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


class StubParseService:
    def __init__(self):
        self.calls = []
        self.engines_seen = []
        self.created_engines = 0

    def create_engine(self, engine_name="simple", **kwargs):
        self.created_engines += 1
        return f"engine-{self.created_engines}"

    def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        self.calls.append((Path(file_path), engine_name, kwargs))
        self.engines_seen.append(engine)
        return ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine=engine_name,
            pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
            markdown_content="Hello",
            metadata={},
        )

    def chunk_result(self, parsed, chunker=None):
        return []

    def render_output(self, parsed, fmt, chunks=None):
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


def test_batch_service_builds_one_engine_for_the_whole_run(tmp_path):
    pdfs = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.pdf"
        path.write_text("x", encoding="utf-8")
        pdfs.append(path)

    parse_service = StubParseService()
    BatchParseService(parse_service=parse_service).run(
        pdfs,
        output_dir=tmp_path / "out",
        max_workers=1,
    )

    assert parse_service.created_engines == 1
    assert parse_service.engines_seen == ["engine-1"] * 3


def test_batch_service_shares_one_engine_across_concurrent_workers(tmp_path):
    pdfs = []
    for name in ("a", "b", "c", "d"):
        path = tmp_path / f"{name}.pdf"
        path.write_text("x", encoding="utf-8")
        pdfs.append(path)

    parse_service = StubParseService()
    BatchParseService(parse_service=parse_service).run(
        pdfs,
        output_dir=tmp_path / "out",
        max_workers=4,
    )

    assert parse_service.created_engines == 1
    assert set(parse_service.engines_seen) == {"engine-1"}


def test_batch_service_keeps_same_stem_sources_in_separate_outputs(tmp_path):
    first = tmp_path / "alpha" / "report.pdf"
    second = tmp_path / "beta" / "report.pdf"
    for path in (first, second):
        path.parent.mkdir(parents=True)
        path.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"

    result = BatchParseService(parse_service=StubParseService()).run(
        [first, second],
        output_dir=output_dir,
        fmt="markdown",
        max_workers=1,
    )

    written = {item.output_path for item in result.items}
    assert len(written) == 2, f"outputs collided: {written}"
    assert result.success_count == 2


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


def test_batch_service_does_not_forward_collect_metrics_to_parser(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    parse_service = StubParseService()
    BatchParseService(parse_service=parse_service).run(
        [pdf],
        output_dir=tmp_path / "out",
        max_workers=1,
        collect_metrics=True,
    )

    assert parse_service.calls == [(pdf, "simple", {})]


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


def test_batch_expand_inputs_picks_up_every_supported_format(tmp_path):
    for name in ("a.pdf", "b.docx", "c.md", "d.xlsx", "ignore.zip"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    found = BatchParseService().expand_inputs([tmp_path])

    assert [path.name for path in found] == ["a.pdf", "b.docx", "c.md", "d.xlsx"]


def test_batch_keeps_same_stem_different_format_side_by_side(tmp_path):
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    for name in ("report.pdf", "report.docx"):
        (source_dir / name).write_text("x", encoding="utf-8")

    result = BatchParseService(parse_service=StubParseService()).run(
        [source_dir],
        output_dir=tmp_path / "out",
        fmt="markdown",
        max_workers=1,
    )

    outputs = [Path(item.output_path) for item in result.items]
    assert len({str(path) for path in outputs}) == 2
    # Same source directory must not be split across different output directories.
    assert len({path.parent for path in outputs}) == 1
    assert all("report" in path.name for path in outputs)
