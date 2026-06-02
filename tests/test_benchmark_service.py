import json

from langparse.metrics import BatchItemResult, BatchRunResult, ParseMetrics
from langparse.services.benchmark_service import BenchmarkService


class StubBatchService:
    def run(self, inputs, engine_name="simple", output_dir="out", fmt="json", max_workers=1, **kwargs):
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
