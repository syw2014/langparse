from dataclasses import asdict

from langparse.types import Chunk, ParsedDocumentResult, ParseDiagnostics, ParsedStructure


def test_parsed_result_accepts_structure_chunks_and_diagnostics():
    structure = ParsedStructure(kind="demo")
    diagnostics = ParseDiagnostics(status="partial", coverage_ratio=0.75)
    chunk = Chunk(content="hello", structured_payload={"rows": [1]})

    parsed = ParsedDocumentResult(
        source="book.xlsx",
        filename="book.xlsx",
        engine="excel",
        structure=structure,
        chunks=[chunk],
        diagnostics=diagnostics,
    )

    payload = asdict(parsed)
    assert payload["structure"] == {"kind": "demo"}
    assert payload["chunks"][0]["structured_payload"] == {"rows": [1]}
    assert payload["diagnostics"]["status"] == "partial"


def test_new_result_fields_are_backward_compatible_defaults():
    parsed = ParsedDocumentResult(source="a.md", filename="a.md", engine="markdown")
    assert parsed.structure is None
    assert parsed.chunks == []
    assert parsed.diagnostics is None
