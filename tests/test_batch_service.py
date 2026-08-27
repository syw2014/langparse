import json
from pathlib import Path
from threading import Lock

import pytest
from openpyxl import Workbook

from langparse.metrics import BatchRunResult
from langparse.services.batch_service import BatchParseService
from langparse.services.parse_service import ParseService
from langparse.types import Chunk, ParsedDocumentResult, ParsedPageResult
from langparse.workbooks.modeling import (
    ModelIdentity,
    ProviderReply,
    WorkbookDisambiguation,
)


class StubParseService:
    def __init__(self):
        self.calls = []
        self.engines_seen = []
        self.profiles_seen = []
        self.disambiguations_seen = []
        self.engine_kwargs_seen = []
        self.engine_creation_kwargs = []
        self.created_engines = 0

    def create_engine(self, engine_name="simple", **kwargs):
        self.created_engines += 1
        self.engine_creation_kwargs.append(kwargs)
        return f"engine-{self.created_engines}"

    def parse_result(
        self,
        file_path,
        engine_name="simple",
        engine=None,
        chunk=False,
        chunk_profile=None,
        workbook_disambiguation=None,
        **kwargs,
    ):
        self.calls.append((Path(file_path), engine_name, kwargs))
        self.engines_seen.append(engine)
        self.profiles_seen.append((chunk, chunk_profile))
        self.disambiguations_seen.append(workbook_disambiguation)
        self.engine_kwargs_seen.append(kwargs)
        result = ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine=engine_name,
            pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
            markdown_content="Hello",
            metadata={},
        )
        if chunk:
            result.chunks = [
                Chunk(
                    content="analysis",
                    metadata={
                        "chunk_profile": chunk_profile,
                        "chunk_profile_version": 1,
                    },
                )
            ]
        return result

    def chunk_result(self, parsed, chunker=None):
        raise AssertionError("BatchParseService must not chunk a parsed result twice")

    def render_output(self, parsed, fmt, chunks=None):
        return parsed.markdown_content if fmt == "markdown" else "{}"


class SelectingAdapter:
    identity = ModelIdentity(provider="scripted", model="fixture", revision="1")

    def __init__(self) -> None:
        self.requests = []

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        self.requests.append((request, timeout_seconds))
        envelope = json.loads(request.body)
        case = envelope["cases"][0]
        selected = next(choice for choice in case["choices"] if choice["kind"] == "text")
        return ProviderReply(
            body=json.dumps(
                {
                    "schema_version": envelope["schema_version"],
                    "request_checksum": request.request_checksum,
                    "decisions": [
                        {
                            "case_id": case["case_id"],
                            "status": "selected",
                            "choice_id": selected["choice_id"],
                            "confidence": 0.99,
                            "reason_codes": ["scripted_selection"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


class CapturingParseService(ParseService):
    def __init__(self) -> None:
        self.results = []
        self._results_lock = Lock()

    def parse_result(self, *args, **kwargs):
        result = super().parse_result(*args, **kwargs)
        with self._results_lock:
            self.results.append(result)
        return result


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


def test_batch_service_passes_analysis_profile_to_parse_result_only(tmp_path):
    source = tmp_path / "book.xlsx"
    source.write_text("placeholder", encoding="utf-8")
    parse_service = StubParseService()

    result = BatchParseService(parse_service=parse_service).run(
        [source],
        output_dir=tmp_path / "out",
        max_workers=1,
        chunk=True,
        chunk_profile="analysis",
    )

    assert result.success_count == 1
    assert parse_service.profiles_seen == [(True, "analysis")]
    assert parse_service.engine_kwargs_seen == [{}]


def test_batch_service_reuses_workbook_disambiguation_without_engine_kwargs(tmp_path):
    sources = []
    for name in ("first", "second"):
        source = tmp_path / f"{name}.xlsx"
        source.write_text("placeholder", encoding="utf-8")
        sources.append(source)
    parse_service = StubParseService()
    configured = WorkbookDisambiguation.off()

    result = BatchParseService(parse_service=parse_service).run(
        sources,
        output_dir=tmp_path / "out",
        max_workers=1,
        chunk=True,
        chunk_profile="analysis",
        workbook_disambiguation=configured,
    )

    assert result.success_count == 2
    assert parse_service.disambiguations_seen == [configured, configured]
    assert all(seen is configured for seen in parse_service.disambiguations_seen)
    assert parse_service.profiles_seen == [(True, "analysis"), (True, "analysis")]
    assert parse_service.engine_creation_kwargs == [{}]
    assert parse_service.engine_kwargs_seen == [{}, {}]


def test_concurrent_batch_items_share_thread_safe_workbook_cache(tmp_path):
    sources = []
    for name in ("first", "second"):
        source = tmp_path / f"{name}.xlsx"
        workbook = Workbook()
        workbook.active.title = "Data"
        workbook.active["A1"] = "左上"
        workbook.active["B2"] = "右下"
        workbook.save(source)
        sources.append(source)
    adapter = SelectingAdapter()
    configured = WorkbookDisambiguation.auto(adapter)
    parse_service = CapturingParseService()

    result = BatchParseService(parse_service=parse_service).run(
        sources,
        output_dir=None,
        max_workers=2,
        workbook_disambiguation=configured,
    )

    assert result.success_count == 2
    assert len(adapter.requests) == 1
    assert sorted(
        parsed.diagnostics.model_calls[0]["cache_status"] for parsed in parse_service.results
    ) == ["hit", "miss"]


def test_batch_workbook_disambiguation_does_not_reach_pdf_engine(tmp_path, monkeypatch):
    from langparse.services import parse_service as parse_service_module

    workbook = Workbook()
    workbook.active["A1"] = "value"
    excel = tmp_path / "book.xlsx"
    workbook.save(excel)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    construction_kwargs = {}
    process_kwargs = {}

    class RecordingEngine:
        def __init__(self, **kwargs):
            construction_kwargs.update(kwargs)

        def process_document(self, file_path, **kwargs):
            process_kwargs.update(kwargs)
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="recording",
            )

    monkeypatch.setitem(parse_service_module.ENGINE_MAP, "recording", RecordingEngine)

    result = BatchParseService().run(
        [excel, pdf],
        engine_name="recording",
        output_dir=tmp_path / "out",
        max_workers=1,
        workbook_disambiguation=WorkbookDisambiguation.off(),
    )

    assert result.success_count == 2
    assert "workbook_disambiguation" not in construction_kwargs
    assert "workbook_disambiguation" not in process_kwargs


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
