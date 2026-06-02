from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from langparse.services.batch_service import BatchParseService
from langparse.services.quality import QualityCheck, run_quality_checks


class BenchmarkService:
    def __init__(self, batch_service: BatchParseService | None = None):
        self.batch_service = batch_service or BatchParseService()

    def run(
        self,
        manifest_path,
        output_dir="reports",
        engine_name: str | None = None,
        fmt: str = "json",
        max_workers: int = 1,
        **kwargs,
    ) -> dict:
        manifest = self._load_manifest(manifest_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        rows = []
        for sample in manifest["samples"]:
            sample_engine = engine_name or sample.get("engine", "simple")
            batch_result = self.batch_service.run(
                [sample["path"]],
                engine_name=sample_engine,
                output_dir=output_dir / "outputs",
                fmt=fmt,
                max_workers=max_workers,
                **kwargs,
            )
            item = batch_result.items[0]
            quality = None
            if item.metrics is not None:
                quality = run_quality_checks(
                    item.metrics,
                    self._quality_check_from_dict(sample.get("checks", {})),
                )
            rows.append(
                {
                    "id": sample["id"],
                    "source": sample["path"],
                    "category": sample.get("category"),
                    "features": sample.get("features", []),
                    "status": item.status,
                    "engine": item.engine or sample_engine,
                    "metrics": asdict(item.metrics) if item.metrics else None,
                    "error_type": item.error_type,
                    "error_message": item.error_message,
                    "quality": asdict(quality) if quality else None,
                }
            )

        summary = self._build_summary(rows)
        self._write_jsonl(output_dir / "benchmark-results.jsonl", rows)
        self._write_json(output_dir / "benchmark-summary.json", summary)
        return {"results": rows, "summary": summary}

    def _load_manifest(self, manifest_path) -> dict:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
            raise ValueError("Benchmark manifest must be a JSON object with a samples list.")
        return payload

    def _quality_check_from_dict(self, payload: dict) -> QualityCheck:
        valid_keys = QualityCheck.__dataclass_fields__.keys()
        return QualityCheck(**{key: value for key, value in payload.items() if key in valid_keys})

    def _build_summary(self, rows: list[dict]) -> dict:
        quality_rows = [row for row in rows if row["quality"] is not None]
        return {
            "total_samples": len(rows),
            "success_count": sum(1 for row in rows if row["status"] == "success"),
            "failed_count": sum(1 for row in rows if row["status"] == "failed"),
            "quality_passed_count": sum(1 for row in quality_rows if row["quality"]["passed"]),
            "quality_failed_count": sum(1 for row in quality_rows if not row["quality"]["passed"]),
            "failed_samples": [row["id"] for row in rows if row["status"] == "failed"],
            "quality_failed_samples": [
                row["id"] for row in quality_rows if not row["quality"]["passed"]
            ],
            "pdf_quality_summary": self._pdf_quality_summary(rows),
        }

    def _pdf_quality_summary(self, rows: list[dict]) -> dict:
        metrics = [row["metrics"] for row in rows if row["metrics"]]
        return {
            "total_tables": sum(item["table_count"] for item in metrics),
            "total_images": sum(item["image_count"] for item in metrics),
            "ocr_applied_count": sum(1 for item in metrics if item["ocr_applied"]),
            "reading_order_warning_count": sum(item["reading_order_warnings"] for item in metrics),
            "header_footer_removed_count": sum(
                item["header_footer_removed_count"] for item in metrics
            ),
        }

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
