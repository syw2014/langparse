"""Chunking must reach the CLI and the metrics layer, not just the library."""

import json

from langparse.cli import main
from langparse.services.batch_service import BatchParseService
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


def _parsed():
    return ParsedDocumentResult(
        source="a.md",
        filename="a.md",
        engine="markdown",
        pages=[ParsedPageResult(page_number=1, markdown_content="# A\n\nbody\n\n# B\n\nbody")],
        markdown_content="# A\n\nbody\n\n# B\n\nbody",
    )


def test_parse_service_produces_chunks_from_a_result():
    chunks = ParseService().chunk_result(_parsed())

    assert [c.metadata["header"] for c in chunks] == ["A", "B"]


def test_json_output_carries_chunks_when_asked():
    service = ParseService()
    parsed = _parsed()

    payload = json.loads(service.render_output(parsed, "json", chunks=service.chunk_result(parsed)))

    assert len(payload["chunks"]) == 2
    assert payload["chunks"][0]["metadata"]["header"] == "A"


def test_json_output_has_no_chunks_key_by_default():
    payload = json.loads(ParseService().render_output(_parsed(), "json"))

    assert "chunks" not in payload


def test_markdown_output_separates_chunks_with_a_rule():
    service = ParseService()
    parsed = _parsed()

    rendered = service.render_output(parsed, "markdown", chunks=service.chunk_result(parsed))

    assert "\n---\n" in rendered


def test_cli_chunk_flag_emits_chunks(tmp_path, capsys):
    source = tmp_path / "note.md"
    source.write_text("# A\n\nbody\n\n# B\n\nbody\n", encoding="utf-8")

    exit_code = main(["parse", str(source), "--chunk", "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["chunks"]) == 2


def test_batch_metrics_count_chunks_when_chunking_is_on(tmp_path):
    source = tmp_path / "note.md"
    source.write_text("# A\n\nbody\n\n# B\n\nbody\n", encoding="utf-8")

    result = BatchParseService().run(
        [source],
        output_dir=tmp_path / "out",
        fmt="json",
        max_workers=1,
        chunk=True,
    )

    metrics = result.items[0].metrics
    assert metrics.chunk_count == 2
    assert metrics.chunks_with_page_numbers_ratio == 1.0
