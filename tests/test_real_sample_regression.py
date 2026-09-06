"""The local acceptance runner must catch loss even when parser diagnostics pass."""

from __future__ import annotations

import json
from copy import deepcopy

import openpyxl
import pytest

from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult
from scripts import verify_real_samples


@pytest.fixture
def runner():
    return verify_real_samples


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "input" / "book.xlsx"
    path.parent.mkdir()
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append(["Item", "Amount"])
    sheet.append(["<script>private</script>", 12])
    sheet.append(["Total", "=SUM(B2:B2)"])
    sheet.merge_cells("D1:E1")
    sheet["D1"] = "Note"
    book.save(path)
    book.close()
    return path


def test_source_comparison_detects_wrong_value_despite_green_diagnostics(runner, workbook):
    parsed = ParseService().parse_result(workbook)
    parsed.structure.snapshot.sheets[0].cells["B2"].raw_value = 99
    result = runner.compare_workbook(workbook, parsed)
    assert result["status"] == "failed"
    assert {"code": "cell_value_mismatch", "sheet": "Data", "cell": "B2"} in result["differences"]


def test_source_comparison_checks_formulas_merges_and_added_cells(runner, workbook):
    parsed = ParseService().parse_result(workbook)
    sheet = parsed.structure.snapshot.sheets[0]
    sheet.cells["B3"].formula = "=SUM(B1:B2)"
    sheet.merged_ranges = []
    sheet.cells["Z1"] = deepcopy(sheet.cells["B2"])
    result = runner.compare_workbook(workbook, parsed)
    codes = {d["code"] for d in result["differences"]}
    assert {"formula_mismatch", "merged_ranges_mismatch", "unexpected_cell"} <= codes


def test_source_comparison_accepts_real_round_trip(runner, workbook):
    result = runner.compare_workbook(workbook, ParseService().parse_result(workbook))
    assert result["status"] == "passed"
    assert result["nonempty_cells"] == 7
    assert result["formula_cells"] == 1


def test_independent_header_check_rejects_title_pollution(runner, workbook):
    parsed = ParseService().parse_result(workbook)
    table = next(b.logical_table for b in parsed.structure.sheets[0].blocks if b.logical_table)
    table.columns[0].path.insert(0, "An unrelated project title")
    checks = [{"kind": "header", "sheet": "Data", "column": "A", "source_cells": ["A1"]}]
    result = runner.check_semantics(workbook, parsed, checks)
    assert result[0]["status"] == "failed"
    assert result[0]["expected"] == ["Item"]


def test_chunk_checks_catch_duplicate_and_missing_rows(runner, workbook):
    service = ParseService()
    parsed = service.parse_result(workbook, chunk=True)
    chunks = service.chunk_result(parsed, chunk_profile="analysis")
    table_chunk = next(c for c in chunks if c.metadata["chunk_type"] == "table_rows")
    table_chunk.metadata["row_ids"] = ["invented-row", "invented-row"]
    result = runner.check_chunks(parsed, chunks)
    assert result["status"] == "failed"
    assert result["duplicates"] == 1
    assert result["missing"] > 0


@pytest.mark.parametrize("corruption", ["row_value", "record_value", "source_ref"])
def test_chunk_payload_and_references_must_match_their_logical_rows(runner, workbook, corruption):
    service = ParseService()
    parsed = service.parse_result(workbook)
    chunks = service.chunk_result(parsed, chunk_profile="analysis")
    chunk = next(c for c in chunks if c.metadata["chunk_type"] == "table_rows")
    if corruption == "row_value":
        chunk.structured_payload["rows"][0][1] = "999"
    elif corruption == "record_value":
        chunk.structured_payload["records"][0]["values"][1] = "999"
    else:
        chunk.metadata["source_ranges"][0] = "Invented!Z99:Z99"
    result = runner.check_chunks(parsed, chunks)
    assert result["status"] == "failed"
    assert result["payload_mismatches"] > 0


def test_pdf_check_rejects_watermark_only_success(runner):
    source = [{"page": 1, "native_text_chars": 120, "requires_ocr": True}]
    parsed = ParsedDocumentResult(
        "scan.pdf",
        "scan.pdf",
        "simple",
        pages=[ParsedPageResult(1, "watermark", metadata={"ocr_applied": False})],
    )
    result = runner.check_pdf(source, parsed)
    assert result["status"] == "failed"
    assert "scan_without_ocr" in {d["code"] for d in result["differences"]}


@pytest.mark.parametrize("engine_name", ["simple", "deepdoc"])
def test_runner_records_explicit_local_pdf_engine(runner, tmp_path, monkeypatch, engine_name):
    source = tmp_path / "inputs" / "scan.pdf"
    source.parent.mkdir()
    source.write_bytes(b"synthetic PDF stand-in")
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([source], manifest)
    monkeypatch.setattr(runner, "_pdf_source", lambda *args: [{"page": 1, "requires_ocr": True}])
    calls = []

    def parse(self, path, **kwargs):
        calls.append(kwargs)
        return ParsedDocumentResult(
            str(path),
            path.name,
            engine_name,
            pages=[ParsedPageResult(1, "recovered", metadata={"ocr_applied": True})],
        )

    monkeypatch.setattr(ParseService, "parse_result", parse)
    result = runner.run(manifest, tmp_path / "output", pdf_engine=engine_name)

    assert result["status"] == "passed"
    assert result["pdf_engine"] == engine_name
    assert calls[0]["engine_name"] == engine_name
    if engine_name == "deepdoc":
        assert calls[0]["model_policy"] == "require_existing"


def test_runner_rejects_remote_pdf_engine_before_creating_output(runner, tmp_path):
    with pytest.raises(ValueError, match="local PDF engine"):
        runner.run(tmp_path / "manifest.json", tmp_path / "output", pdf_engine="mineru")
    assert not (tmp_path / "output").exists()


def test_source_annotated_pdf_table_is_not_satisfied_by_plain_ocr_text(runner, tmp_path):
    parsed = ParsedDocumentResult(
        "scan.pdf",
        "scan.pdf",
        "simple",
        pages=[
            ParsedPageResult(
                1, "Recognised text without table cells", metadata={"ocr_applied": True}
            )
        ],
    )
    checks = [{"kind": "pdf_table", "page": 1, "minimum": 1}]
    result = runner.check_semantics(tmp_path / "scan.pdf", parsed, checks)
    assert result[0]["status"] == "failed"
    assert result[0]["actual"] == 0


def test_source_change_during_parse_cannot_produce_a_passing_report(
    runner, workbook, tmp_path, monkeypatch
):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    original = ParseService.parse_result

    def changing_parse(self, path, **kwargs):
        parsed = original(self, path, **kwargs)
        path.write_bytes(path.read_bytes() + b"changed during parsing")
        return parsed

    monkeypatch.setattr(ParseService, "parse_result", changing_parse)
    result = runner.run(manifest, tmp_path / "report")
    assert result["status"] == "failed"
    assert result["samples"][0]["failure"] == "source_changed_during_run"


def test_cli_returns_nonzero_for_semantic_failures(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    data = json.loads(manifest.read_text())
    data["samples"][0]["semantic_checks"] = [
        {"kind": "row_role", "sheet": "Data", "source_range": "A1:B1", "expected": "total"}
    ]
    manifest.write_text(json.dumps(data))
    assert (
        runner.main(["run", "--manifest", str(manifest), "--output-dir", str(tmp_path / "report")])
        == 1
    )


def test_manifest_duplicate_fields_are_rejected(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    manifest.write_text(
        manifest.read_text().replace(
            '"split": "regression"', '"split": "holdout", "split": "regression"'
        )
    )
    with pytest.raises(ValueError, match="duplicate"):
        runner.run(manifest, tmp_path / "report")


def test_manifest_hash_drift_is_failure_and_original_is_untouched(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    workbook.write_bytes(workbook.read_bytes() + b"source changed")
    before = workbook.read_bytes()
    result = runner.run(manifest, tmp_path / "report")
    assert result["status"] == "failed"
    assert result["samples"][0]["failure"] == "source_hash_mismatch"
    assert workbook.read_bytes() == before


def test_report_is_reviewable_and_does_not_certify_unlabelled_data(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    output = tmp_path / "report"
    result = runner.run(manifest, output)
    assert result["status"] == "passed"
    assert result["split"] == "regression"
    assert result["production_ready"] is False
    assert result["business_review_status"] == "pending"
    page = (output / "sample-001" / "review.html").read_text()
    assert "&lt;script&gt;private&lt;/script&gt;" in page
    assert "<script>private</script>" not in page
    assert (output / "summary.json").is_file()
    with pytest.raises(FileExistsError):
        runner.run(manifest, output)


def test_output_cannot_overlap_input_directory(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    with pytest.raises(ValueError, match="overlap"):
        runner.run(manifest, workbook.parent / "report")


def test_no_private_sample_is_silently_skipped(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    workbook.unlink()
    result = runner.run(manifest, tmp_path / "report")
    assert result["status"] == "failed"
    assert result["samples"][0]["failure"] == "source_missing"


def test_manifest_rejects_unsafe_ids_and_empty_samples(runner, workbook, tmp_path):
    manifest = tmp_path / "manifest.json"
    runner.create_manifest([workbook], manifest)
    data = json.loads(manifest.read_text())
    data["samples"][0]["id"] = "../outside"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        runner.run(manifest, tmp_path / "report")
    data["samples"] = []
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        runner.run(manifest, tmp_path / "report")
