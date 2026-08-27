import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from langparse.core.engine import PageResult
from langparse.metrics import collect_parse_metrics
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult, ParsedStructure
from langparse.workbooks.modeling import (
    ModelIdentity,
    ProviderReply,
    RequiredWorkbookDisambiguationError,
    WorkbookDisambiguation,
)


class SelectingAdapter:
    def __init__(self, *, kind: str) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")
        self.kind = kind
        self.requests = []

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        self.requests.append((request, timeout_seconds))
        envelope = json.loads(request.body)
        case = envelope["cases"][0]
        selected = next(choice for choice in case["choices"] if choice["kind"] == self.kind)
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


class AbstainingAdapter:
    def __init__(self) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        envelope = json.loads(request.body)
        case = envelope["cases"][0]
        return ProviderReply(
            body=json.dumps(
                {
                    "schema_version": envelope["schema_version"],
                    "request_checksum": request.request_checksum,
                    "decisions": [
                        {
                            "case_id": case["case_id"],
                            "status": "abstained",
                            "choice_id": None,
                            "confidence": 0.0,
                            "reason_codes": ["scripted_abstention"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


class MalformedAdapter:
    def __init__(self, shape: str) -> None:
        self.identity = (
            object()
            if shape == "identity"
            else ModelIdentity(provider="scripted", model="fixture", revision="1")
        )
        self.shape = shape

    def complete(self, request, *, timeout_seconds: float):
        assert self.shape == "reply"
        return SimpleNamespace(body="private malformed reply")


def sparse_workbook(tmp_path):
    path = tmp_path / "sparse.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "左上"
    sheet["B2"] = "右下"
    workbook.save(path)
    return path


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
            raise AssertionError(
                "process() should not be used after invalid process_document output"
            )

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


def test_parse_result_chunk_flag_does_not_reach_pdf_engine(tmp_path):
    seen = {}

    class FastPathEngine:
        def process_document(self, file_path, **kwargs):
            seen.update(kwargs)
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                pages=[ParsedPageResult(page_number=1, markdown_content="# Title\n\nBody")],
                markdown_content="# Title\n\nBody",
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    parsed = ParseService().parse_result(pdf, engine=FastPathEngine(), chunk=True)

    assert "chunk" not in seen
    assert parsed.chunks


def test_parse_service_passes_workbook_disambiguation_only_to_excel(tmp_path):
    source = sparse_workbook(tmp_path)
    adapter = SelectingAdapter(kind="text")
    configured = WorkbookDisambiguation.auto(adapter)

    parsed = ParseService().parse_result(
        source,
        workbook_disambiguation=configured,
    )

    assert parsed.structure.sheets[0].blocks[0].kind == "text"
    assert len(adapter.requests) == 1


def test_parse_service_reuses_configured_workbook_cache_across_calls(tmp_path):
    source = sparse_workbook(tmp_path)
    adapter = SelectingAdapter(kind="text")
    configured = WorkbookDisambiguation.auto(adapter)
    service = ParseService()

    first = service.parse_result(source, workbook_disambiguation=configured)
    second = service.parse_result(source, workbook_disambiguation=configured)

    assert len(adapter.requests) == 1
    assert first.diagnostics.model_calls[0]["cache_status"] == "miss"
    assert second.diagnostics.model_calls[0]["cache_status"] == "hit"
    assert second.diagnostics.model_calls[0]["attempts"] == 0


def test_workbook_disambiguation_does_not_reach_pdf_engine(tmp_path):
    seen = {}
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    class RecordingEngine:
        def process_document(self, file_path, **kwargs):
            seen.update(kwargs)
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="recording",
            )

    ParseService().parse_result(
        pdf,
        engine=RecordingEngine(),
        workbook_disambiguation=WorkbookDisambiguation.off(),
    )

    assert "workbook_disambiguation" not in seen


def test_parse_service_propagates_required_workbook_disambiguation_error(tmp_path):
    source = sparse_workbook(tmp_path)

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        ParseService().parse_result(
            source,
            workbook_disambiguation=WorkbookDisambiguation.required(AbstainingAdapter()),
        )

    assert caught.value.case_ids
    assert caught.value.diagnostics.status == "failed"


@pytest.mark.parametrize("shape", ["identity", "reply"])
@pytest.mark.parametrize("mode", ["auto", "required"])
def test_parse_service_contains_malformed_workbook_adapter_boundaries(
    tmp_path,
    shape: str,
    mode: str,
):
    source = sparse_workbook(tmp_path)
    configured = getattr(WorkbookDisambiguation, mode)(MalformedAdapter(shape))

    if mode == "auto":
        parsed = ParseService().parse_result(
            source,
            workbook_disambiguation=configured,
        )
        assert parsed.structure.sheets[0].blocks[0].kind == "unclassified"
        assert parsed.diagnostics.model_calls
    else:
        with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
            ParseService().parse_result(
                source,
                workbook_disambiguation=configured,
            )
        parsed = caught.value

    assert "private malformed reply" not in repr(parsed)


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


def test_write_batch_outputs_keeps_same_dir_siblings_together(tmp_path):
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    outputs = [
        (source_dir / "report.pdf", "from pdf"),
        (source_dir / "report.docx", "from docx"),
    ]

    written = ParseService().write_batch_outputs(outputs, tmp_path / "out", "markdown")

    assert len(set(written)) == 2
    assert len({path.parent for path in written}) == 1
    assert all("report" in path.name for path in written)


def test_chunk_option_does_not_leak_into_engine_config(tmp_path):
    """Rendering options must not be forwarded as engine construction kwargs.

    MinerU folds unknown kwargs into extra_options and sends them to its API as
    form fields, so a leak here becomes a bogus request parameter.
    """
    from langparse.services import parse_service as module

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    seen = {}

    class RecordingEngine:
        def __init__(self, **config):
            seen.update(config)

        def process(self, file_path, **kwargs):
            return iter(())

    module.ENGINE_MAP["recording"] = RecordingEngine
    try:
        ParseService().parse_batch_outputs([pdf], engine_name="recording", fmt="json", chunk=True)
    finally:
        module.ENGINE_MAP.pop("recording", None)

    assert "chunk" not in seen


def test_parse_service_reuses_one_workbook_result_for_both_profiles(sample_excel_file):
    service = ParseService()
    parsed = service.parse_result(sample_excel_file, chunk=True)
    original_chunks = list(parsed.chunks)

    analysis = service.chunk_result(parsed, chunk_profile="analysis")

    assert {chunk.metadata["chunk_profile"] for chunk in parsed.chunks} == {"retrieval"}
    assert {chunk.metadata["chunk_profile"] for chunk in analysis} == {"analysis"}
    assert parsed.chunks == original_chunks


def test_explicit_profile_and_custom_chunker_are_mutually_exclusive():
    parsed = ParsedDocumentResult(source="a.md", filename="a.md", engine="markdown")

    with pytest.raises(
        ValueError,
        match="custom chunker and chunk_profile are mutually exclusive",
    ):
        ParseService().chunk_result(parsed, chunker=object(), chunk_profile="retrieval")


def test_direct_analysis_chunking_rejects_non_workbook_results():
    parsed = ParsedDocumentResult(
        source="a.md",
        filename="a.md",
        engine="markdown",
        markdown_content="# A",
    )

    with pytest.raises(ValueError, match="analysis chunk profile requires WorkbookIR"):
        ParseService().chunk_result(parsed, chunk_profile="analysis")


def test_direct_analysis_chunking_rejects_non_rich_workbook_structure():
    parsed = ParsedDocumentResult(
        source="legacy.xls",
        filename="legacy.xls",
        engine="excel",
        markdown_content="# Legacy workbook",
        structure=ParsedStructure(kind="workbook"),
    )

    with pytest.raises(ValueError, match="analysis chunk profile requires WorkbookIR"):
        ParseService().chunk_result(parsed, chunk_profile="analysis")


def test_parse_result_marks_non_rich_workbook_analysis_as_unsupported(tmp_path):
    class LegacyWorkbookEngine:
        def process_document(self, file_path, **kwargs):
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="legacy-workbook",
                markdown_content="# Legacy workbook",
                structure=ParsedStructure(kind="workbook"),
            )

    pdf = tmp_path / "legacy.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    parsed = ParseService().parse_result(
        pdf,
        engine=LegacyWorkbookEngine(),
        chunk=True,
        chunk_profile="analysis",
    )

    assert parsed.chunks == []
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.status == "partial"
    assert parsed.diagnostics.errors == []
    assert parsed.diagnostics.unsupported_features == [
        "Chunking profile 'analysis' is not supported for engine 'legacy-workbook'."
    ]


def test_non_workbook_chunks_are_tagged_as_retrieval(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n\nBody", encoding="utf-8")

    parsed = ParseService().parse_result(source, chunk=True)

    assert parsed.chunks
    assert {chunk.metadata["chunk_profile"] for chunk in parsed.chunks} == {"retrieval"}
    assert {chunk.metadata["chunk_profile_version"] for chunk in parsed.chunks} == {1}


def test_invalid_profile_fails_before_pdf_engine_runs(tmp_path):
    called = False

    class RecordingEngine:
        def process_document(self, file_path, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("engine must not run")

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="Unknown workbook chunk profile"):
        ParseService().parse_result(
            pdf,
            engine=RecordingEngine(),
            chunk=True,
            chunk_profile="balanced",
        )
    assert called is False


def test_chunk_false_ignores_profile_and_does_not_forward_it_to_engine(tmp_path):
    seen = {}

    class RecordingEngine:
        def process_document(self, file_path, **kwargs):
            seen.update(kwargs)
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                markdown_content="Hello",
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    parsed = ParseService().parse_result(
        pdf,
        engine=RecordingEngine(),
        chunk=False,
        chunk_profile="not-used",
    )

    assert parsed.markdown_content == "Hello"
    assert "chunk_profile" not in seen


def test_parse_result_preserves_workbook_when_chunker_fails(sample_excel_file, monkeypatch):
    def fail_chunk(self, parsed):
        raise RuntimeError("sensitive cell value must not be copied")

    monkeypatch.setattr(
        "langparse.chunkers.workbook.WorkbookStructuralChunker.chunk",
        fail_chunk,
    )
    service = ParseService()

    parsed = service.parse_result(sample_excel_file, chunk=True)

    assert parsed.structure is not None
    assert parsed.markdown_content
    assert parsed.chunks == []
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.status == "partial"
    assert parsed.diagnostics.errors == ["Chunking profile 'retrieval' failed (RuntimeError)."]
    assert "sensitive cell value" not in str(parsed.diagnostics.errors)
    assert service.render_output(parsed, "markdown", chunks=[]) == parsed.markdown_content


def test_parse_result_preserves_non_workbook_when_analysis_is_unsupported(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n\nBody", encoding="utf-8")

    parsed = ParseService().parse_result(source, chunk=True, chunk_profile="analysis")

    assert parsed.markdown_content == "# A\n\nBody"
    assert parsed.chunks == []
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.status == "partial"
    assert parsed.diagnostics.unsupported_features == [
        "Chunking profile 'analysis' is not supported for engine 'markdown'."
    ]
