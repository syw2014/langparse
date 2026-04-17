import json
from pathlib import Path

import pytest

from langparse.cli import build_parser, main
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


def test_cli_accepts_parse_command():
    parser = build_parser()
    args = parser.parse_args(["parse", "sample.pdf", "--engine", "mineru", "--format", "markdown"])

    assert args.command == "parse"
    assert args.engine == "mineru"
    assert args.format == "markdown"


def test_cli_batch_command_supports_output_dir():
    parser = build_parser()
    args = parser.parse_args(["parse", "docs/", "--batch", "--output-dir", "out"])

    assert args.batch is True
    assert args.output_dir == "out"


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
        ("parse_output", "sample.pdf", "mineru", "json", {"device": "cpu"}),
        ("write_output", "rendered", Path("out.json")),
    ]


def test_cli_main_batch_parse_delegates_to_service(monkeypatch, capsys):
    calls = []

    class FakeService:
        def parse_batch_outputs(self, inputs, engine_name="simple", fmt="markdown", **kwargs):
            calls.append(("parse_batch_outputs", inputs, engine_name, fmt, kwargs))
            return [(Path("a.pdf"), "first"), (Path("b.pdf"), "second")]

        def write_batch_outputs(self, outputs, output_dir, fmt):
            calls.append(("write_batch_outputs", outputs, output_dir, fmt))
            return []

    monkeypatch.setattr("langparse.cli.ParseService", FakeService)

    exit_code = main(["parse", "docs", "--batch"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "first\nsecond\n"
    assert calls == [
        ("parse_batch_outputs", ["docs"], "simple", "markdown", {}),
    ]
