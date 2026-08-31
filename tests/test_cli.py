import json
from datetime import date
from pathlib import Path

import pytest

from langparse.cli import build_parser, main
from langparse.metrics import BatchRunResult
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


def test_cli_accepts_parse_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "parse",
            "sample.pdf",
            "--engine",
            "mineru",
            "--format",
            "markdown",
            "--api-url",
            "http://mineru.example:8000",
            "--model-policy",
            "require_existing",
        ]
    )

    assert args.command == "parse"
    assert args.engine == "mineru"
    assert args.format == "markdown"
    assert args.api_url == "http://mineru.example:8000"
    assert args.model_policy == "require_existing"


def test_cli_accepts_mineru_runtime_install_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "parse",
            "sample.pdf",
            "--engine",
            "mineru",
            "--auto-install-runtime",
            "--runtime-package",
            "mineru[all]",
        ]
    )

    assert args.auto_install_runtime is True
    assert args.runtime_package == "mineru[all]"


def test_cli_batch_command_supports_output_dir():
    parser = build_parser()
    args = parser.parse_args(
        ["parse", "docs/", "--batch", "--output-dir", "out", "--api-port", "8010"]
    )

    assert args.batch is True
    assert args.output_dir == "out"
    assert args.api_port == 8010


def test_cli_accepts_analysis_chunk_profile():
    args = build_parser().parse_args(
        ["parse", "book.xlsx", "--chunk", "--chunk-profile", "analysis"]
    )

    assert args.chunk is True
    assert args.chunk_profile == "analysis"


def test_cli_main_help_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 0
    assert "usage: langparse" in captured.out


def test_render_output_returns_markdown():
    parsed = ParsedDocumentResult(
        source="sample.pdf",
        filename="sample.pdf",
        engine="simple",
        pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
        markdown_content="Hello",
        metadata={"kind": "demo"},
    )

    assert ParseService().render_output(parsed, "markdown") == "Hello"


def test_render_output_returns_json():
    parsed = ParsedDocumentResult(
        source="sample.pdf",
        filename="sample.pdf",
        engine="simple",
        pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
        markdown_content="Hello",
        metadata={"kind": "demo"},
    )

    rendered = ParseService().render_output(parsed, "json")

    assert json.loads(rendered)["metadata"] == {"kind": "demo"}


def test_render_output_serializes_excel_native_date_values():
    from langparse.workbooks.types import (
        CellSnapshot,
        SheetSnapshot,
        WorkbookIR,
        WorkbookSnapshot,
    )

    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                cells={"A1": CellSnapshot(coordinate="A1", raw_value=date(2026, 8, 25))},
            )
        ],
    )
    parsed = ParsedDocumentResult(
        source="book.xlsx",
        filename="book.xlsx",
        engine="excel",
        structure=WorkbookIR(
            kind="workbook",
            workbook_id="wb-1",
            source="book.xlsx",
            snapshot=snapshot,
        ),
    )

    payload = json.loads(ParseService().render_output(parsed, "json"))

    assert payload["structure"]["snapshot"]["sheets"][0]["cells"]["A1"]["raw_value"] == (
        "2026-08-25"
    )


def test_render_output_rejects_unknown_format():
    parsed = ParsedDocumentResult(
        source="sample.pdf",
        filename="sample.pdf",
        engine="simple",
        pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
        markdown_content="Hello",
        metadata={},
    )

    with pytest.raises(ValueError, match="Unsupported output format: text"):
        ParseService().render_output(parsed, "text")


def test_parse_batch_outputs_returns_rendered_content(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_text("x")

    parsed = ParsedDocumentResult(
        source=str(pdf),
        filename=pdf.name,
        engine="simple",
        pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
        markdown_content="Hello",
        metadata={},
    )

    service = ParseService()
    outputs = service.parse_batch_outputs(
        [pdf],
        engine_name="simple",
        fmt="markdown",
        engine=type("Engine", (), {"process_document": lambda self, file_path, **kwargs: parsed})(),
    )

    assert outputs == [(pdf, "Hello")]


def test_write_batch_outputs_writes_files(tmp_path):
    service = ParseService()
    output_dir = tmp_path / "out"

    written = service.write_batch_outputs(
        [(tmp_path / "sample.pdf", "Hello")],
        output_dir=output_dir,
        fmt="markdown",
    )

    assert written == [output_dir / "sample.md"]
    assert (output_dir / "sample.md").read_text(encoding="utf-8") == "Hello"


def test_write_batch_outputs_preserves_relative_paths_for_same_basename(tmp_path):
    service = ParseService()
    output_dir = tmp_path / "out"

    written = service.write_batch_outputs(
        [
            (Path("team-a/report.pdf"), "Alpha"),
            (Path("team-b/report.pdf"), "Beta"),
        ],
        output_dir=output_dir,
        fmt="markdown",
    )

    assert written == [
        output_dir / "team-a" / "report.md",
        output_dir / "team-b" / "report.md",
    ]
    assert (output_dir / "team-a" / "report.md").read_text(encoding="utf-8") == "Alpha"
    assert (output_dir / "team-b" / "report.md").read_text(encoding="utf-8") == "Beta"


def test_cli_main_single_parse_delegates_to_service(monkeypatch):
    calls = []

    class FakeService:
        def parse_output(self, file_path, engine_name="simple", fmt="markdown", **kwargs):
            calls.append(("parse_output", file_path, engine_name, fmt, kwargs))
            return "rendered"

        def write_output(self, content, output_path):
            calls.append(("write_output", content, output_path))
            return output_path

    monkeypatch.setattr("langparse.cli.ParseService", FakeService)

    exit_code = main(
        [
            "parse",
            "sample.pdf",
            "--engine",
            "mineru",
            "--format",
            "json",
            "--output",
            "out.json",
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("parse_output", "sample.pdf", "mineru", "json", {"chunk": False, "device": "cpu"}),
        ("write_output", "rendered", Path("out.json")),
    ]


def test_cli_single_parse_forwards_profile_only_as_chunk_option(monkeypatch):
    calls = []

    class FakeService:
        def parse_output(self, file_path, engine_name="simple", fmt="markdown", **kwargs):
            calls.append((file_path, engine_name, fmt, kwargs))
            return "rendered"

    monkeypatch.setattr("langparse.cli.ParseService", FakeService)

    assert main(["parse", "book.xlsx", "--chunk", "--chunk-profile", "analysis"]) == 0
    assert calls == [
        (
            "book.xlsx",
            "simple",
            "markdown",
            {"chunk": True, "chunk_profile": "analysis"},
        )
    ]


def test_cli_main_single_parse_passes_mineru_api_kwargs(monkeypatch):
    calls = []

    class FakeService:
        def parse_output(self, file_path, engine_name="simple", fmt="markdown", **kwargs):
            calls.append(("parse_output", file_path, engine_name, fmt, kwargs))
            return "rendered"

    monkeypatch.setattr("langparse.cli.ParseService", FakeService)

    exit_code = main(
        [
            "parse",
            "sample.pdf",
            "--engine",
            "mineru",
            "--api-url",
            "http://mineru.example:8000",
            "--api-port",
            "8010",
            "--api-command",
            "mineru-api",
            "--api-start-timeout",
            "12",
            "--mineru-request-timeout",
            "900",
            "--mineru-backend",
            "vlm-http-client",
            "--mineru-server-url",
            "http://vlm.example:21670",
            "--model-policy",
            "require_existing",
            "--model-source",
            "local",
            "--auto-install-runtime",
            "--runtime-package",
            "mineru[all]",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            "parse_output",
            "sample.pdf",
            "mineru",
            "markdown",
            {
                "chunk": False,
                "api_url": "http://mineru.example:8000",
                "api_port": 8010,
                "api_command": "mineru-api",
                "api_start_timeout": 12.0,
                "request_timeout": 900.0,
                "backend": "vlm-http-client",
                "server_url": "http://vlm.example:21670",
                "model_policy": "require_existing",
                "model_source": "local",
                "auto_install_runtime": True,
                "runtime_package": "mineru[all]",
            },
        )
    ]


def test_cli_main_batch_delegates_to_batch_service_and_prints(monkeypatch, capsys):
    """Without --output-dir the batch run renders to memory and the CLI prints it."""
    calls = []

    class FakeBatchService:
        def run(self, inputs, **kwargs):
            calls.append((inputs, kwargs))
            return BatchRunResult(rendered_outputs=["first", "second"])

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)

    exit_code = main(["parse", "docs", "--batch"])

    assert exit_code == 0
    assert capsys.readouterr().out == "first\nsecond\n"
    assert calls[0][0] == ["docs"]
    assert calls[0][1]["output_dir"] is None


def test_cli_batch_forwards_profile_outside_engine_kwargs(monkeypatch):
    calls = []

    class FakeBatchService:
        def run(self, inputs, **kwargs):
            calls.append((inputs, kwargs))
            return BatchRunResult()

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)

    assert main(["parse", "books", "--batch", "--chunk", "--chunk-profile", "analysis"]) == 0
    assert calls[0][1]["chunk"] is True
    assert calls[0][1]["chunk_profile"] == "analysis"


def test_cli_parse_accepts_batch_metrics_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "parse",
            "docs/",
            "--batch",
            "--output-dir",
            "out",
            "--max-workers",
            "4",
            "--skip-existing",
            "--metrics",
        ]
    )

    assert args.max_workers == 4
    assert args.skip_existing is True
    assert args.metrics is True


def test_cli_benchmark_command_accepts_manifest_and_output_dir():
    parser = build_parser()
    args = parser.parse_args(
        [
            "benchmark",
            "samples/public.example.json",
            "--engine",
            "mineru",
            "--output-dir",
            "reports",
            "--max-workers",
            "2",
            "--mineru-backend",
            "vlm-http-client",
            "--mineru-server-url",
            "http://vlm.example:21670",
            "--mineru-request-timeout",
            "900",
        ]
    )

    assert args.command == "benchmark"
    assert args.manifest == "samples/public.example.json"
    assert args.engine == "mineru"
    assert args.output_dir == "reports"
    assert args.max_workers == 2


def test_cli_main_batch_metrics_delegates_to_batch_service(monkeypatch):
    calls = []

    class FakeBatchService:
        def run(
            self,
            inputs,
            engine_name="simple",
            output_dir="out",
            fmt="markdown",
            max_workers=None,
            skip_existing=False,
            **kwargs,
        ):
            calls.append((inputs, engine_name, output_dir, fmt, max_workers, skip_existing, kwargs))
            return BatchRunResult()

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)

    exit_code = main(
        [
            "parse",
            "docs/",
            "--batch",
            "--output-dir",
            "out",
            "--engine",
            "mineru",
            "--format",
            "json",
            "--max-workers",
            "4",
            "--skip-existing",
            "--metrics",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (["docs/"], "mineru", "out", "json", 4, True, {"collect_metrics": True, "chunk": False})
    ]


def test_cli_main_benchmark_delegates_to_benchmark_service(monkeypatch):
    calls = []

    class FakeBenchmarkService:
        def run(
            self,
            manifest,
            output_dir="reports",
            engine_name=None,
            fmt="json",
            max_workers=1,
            **kwargs,
        ):
            calls.append((manifest, output_dir, engine_name, fmt, max_workers, kwargs))
            return {"summary": {"total_samples": 1}}

    monkeypatch.setattr("langparse.cli.BenchmarkService", FakeBenchmarkService)

    exit_code = main(
        [
            "benchmark",
            "samples/public.example.json",
            "--engine",
            "mineru",
            "--output-dir",
            "reports",
            "--max-workers",
            "2",
            "--mineru-backend",
            "vlm-http-client",
            "--mineru-server-url",
            "http://vlm.example:21670",
            "--mineru-request-timeout",
            "900",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            "samples/public.example.json",
            "reports",
            "mineru",
            "json",
            2,
            {
                "backend": "vlm-http-client",
                "server_url": "http://vlm.example:21670",
                "request_timeout": 900.0,
            },
        )
    ]


def test_cli_parses_non_pdf_input_without_a_pdf_engine(tmp_path, capsys):
    source = tmp_path / "note.md"
    source.write_text("# Title\n\nBody\n", encoding="utf-8")

    exit_code = main(["parse", str(source)])

    assert exit_code == 0
    assert "# Title" in capsys.readouterr().out


def test_cli_reports_unsupported_extension_without_a_traceback(tmp_path, capsys):
    source = tmp_path / "archive.zip"
    source.write_bytes(b"PK")

    exit_code = main(["parse", str(source)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unsupported file extension" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_missing_file_without_a_traceback(tmp_path, capsys):
    exit_code = main(["parse", str(tmp_path / "nope.pdf")])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "File not found" in captured.err


def test_cli_batch_always_uses_one_implementation(tmp_path, monkeypatch):
    """Plain --batch and flagged --batch must not take different code paths."""
    used = []

    class FakeBatchService:
        def run(self, inputs, **kwargs):
            used.append(kwargs)
            return BatchRunResult()

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)
    source = tmp_path / "a.md"
    source.write_text("# A\n", encoding="utf-8")

    assert main(["parse", str(source), "--batch", "--output-dir", str(tmp_path / "o")]) == 0
    assert (
        main(["parse", str(source), "--batch", "--metrics", "--output-dir", str(tmp_path / "o")])
        == 0
    )

    assert len(used) == 2, "plain --batch bypassed BatchParseService"


def test_cli_plain_batch_writes_into_the_output_dir(tmp_path):
    source_dir = tmp_path / "in"
    source_dir.mkdir()
    (source_dir / "a.md").write_text("# A\n\nbody\n", encoding="utf-8")
    out = tmp_path / "out"

    assert main(["parse", str(source_dir), "--batch", "--output-dir", str(out)]) == 0

    assert list(out.rglob("*.md")), "no output written"
