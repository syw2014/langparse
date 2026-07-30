import json

from langparse.metrics import BatchItemResult, BatchRunResult, ParseMetrics
from langparse.services.benchmark_service import BenchmarkService


class StubBatchService:
    def run(
        self, inputs, engine_name="simple", output_dir="out", fmt="json", max_workers=1, **kwargs
    ):
        return BatchRunResult(
            items=[
                BatchItemResult(
                    source=str(inputs[0]),
                    status="success",
                    metrics=ParseMetrics(
                        page_count=2,
                        markdown_chars=2000,
                        table_count=1,
                        page_marker_coverage=1.0,
                    ),
                    engine=engine_name,
                )
            ]
        )


def test_benchmark_service_loads_manifest_and_writes_reports(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_text("x", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "id": "sample",
                        "path": str(pdf),
                        "category": "paper",
                        "features": ["tables"],
                        "engine": "mineru",
                        "checks": {
                            "min_pages": 1,
                            "min_chars": 10,
                            "min_tables": 1,
                            "require_page_markers": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = BenchmarkService(batch_service=StubBatchService()).run(
        manifest,
        output_dir=tmp_path / "reports",
    )

    assert result["summary"]["total_samples"] == 1
    assert result["summary"]["quality_passed_count"] == 1
    assert (tmp_path / "reports" / "benchmark-results.jsonl").exists()
    assert (tmp_path / "reports" / "benchmark-summary.json").exists()


def test_benchmark_scores_fidelity_against_a_reference(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text("# Title\n\nthe quick brown fox\n", encoding="utf-8")
    reference = tmp_path / "doc.expected.md"
    reference.write_text("# Title\n\nthe quick brown fox\n", encoding="utf-8")

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "id": "s1",
                        "path": str(source),
                        "expected_markdown": str(reference),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="markdown")

    fidelity = report["results"][0]["fidelity"]
    assert fidelity["text_similarity"] == 1.0
    assert report["summary"]["mean_text_similarity"] == 1.0


def test_benchmark_fidelity_drops_when_content_is_missing(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text("# Title\n\nonly this\n", encoding="utf-8")
    reference = tmp_path / "doc.expected.md"
    reference.write_text("# Title\n\nonly this and much much more text here\n", encoding="utf-8")

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {"samples": [{"id": "s1", "path": str(source), "expected_markdown": str(reference)}]}
        ),
        encoding="utf-8",
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="markdown")

    assert report["results"][0]["fidelity"]["text_similarity"] < 1.0


def test_benchmark_scores_tables_with_teds(tmp_path):
    source = tmp_path / "t.csv"
    source.write_text("A,B\n1,2\n", encoding="utf-8")

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "id": "s1",
                        "path": str(source),
                        "expected_tables": [[["A", "B"], ["1", "2"]]],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="json")

    assert report["results"][0]["fidelity"]["teds"] == 1.0
    assert report["summary"]["mean_teds"] == 1.0


def test_benchmark_omits_fidelity_when_no_reference_is_given(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text("# Title\n", encoding="utf-8")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"samples": [{"id": "s1", "path": str(source)}]}), encoding="utf-8"
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="markdown")

    assert report["results"][0]["fidelity"] is None
    assert report["summary"]["mean_text_similarity"] is None


def test_text_fidelity_compares_markdown_regardless_of_output_format(tmp_path):
    """A JSON run writes a dataclass dump; scoring must still compare prose."""
    source = tmp_path / "doc.md"
    source.write_text("# Doc\n\nthe quick brown fox jumps\n", encoding="utf-8")
    reference = tmp_path / "doc.expected.md"
    reference.write_text("# Doc\n\nthe quick brown fox jumps\n", encoding="utf-8")

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {"samples": [{"id": "s1", "path": str(source), "expected_markdown": str(reference)}]}
        ),
        encoding="utf-8",
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="json")

    assert report["results"][0]["fidelity"]["text_similarity"] == 1.0


def test_table_fidelity_works_from_markdown_output(tmp_path):
    source = tmp_path / "t.csv"
    source.write_text("A,B\n1,2\n", encoding="utf-8")

    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "id": "s1",
                        "path": str(source),
                        "expected_tables": [[["A", "B"], ["1", "2"]]],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = BenchmarkService().run(manifest, output_dir=tmp_path / "reports", fmt="markdown")

    assert report["results"][0]["fidelity"]["teds"] == 1.0
