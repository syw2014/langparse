from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from langparse import __version__
from langparse.services.parse_service import ParseService
from langparse.workbooks.evaluation.schema import validate_output_dir_isolation
from langparse.workbooks.quality.evaluator import (
    WORKBOOK_QUALITY_METRIC_SCHEMA_VERSION,
    WorkbookQualityMetrics,
    evaluate_workbook_result,
)
from langparse.workbooks.quality.schema import load_workbook_quality_manifest


class WorkbookQualityReportError(RuntimeError):
    """Raised when a workbook quality report cannot be safely published."""


@dataclass(frozen=True)
class WorkbookQualityBenchmarkReport:
    run_digest: str
    output_path: Path
    summary: dict[str, Any]
    results: tuple[dict[str, Any], ...]


class WorkbookQualityBenchmarkService:
    """Evaluate complete workbook results against versioned structural truth."""

    def __init__(self, parse_service: ParseService | None = None) -> None:
        self._parse_service = parse_service or ParseService()

    def run(
        self,
        manifest_path: str | Path,
        *,
        output_dir: str | Path,
        markdown: bool = True,
    ) -> WorkbookQualityBenchmarkReport:
        manifest = load_workbook_quality_manifest(manifest_path)
        output_root = Path(output_dir).resolve()
        validate_output_dir_isolation(manifest.source_root, output_root)

        sample_results: list[dict[str, Any]] = []
        for sample in manifest.samples:
            sample_path = (manifest.source_root / sample.path).resolve()
            before = _file_identity(sample_path)
            if before[2] != sample.sha256:
                raise WorkbookQualityReportError(
                    f"Source workbook no longer matches manifest: {sample.sample_id}"
                )
            parsed = self._parse_service.parse_result(sample_path)
            metrics = evaluate_workbook_result(sample.expectation, parsed)
            after = _file_identity(sample_path)
            if after != before:
                raise WorkbookQualityReportError(
                    f"Source workbook changed during evaluation: {sample.sample_id}"
                )
            sample_results.append(
                {
                    "sample_id": sample.sample_id,
                    "sha256": sample.sha256,
                    "metrics": asdict(metrics),
                }
            )

        aggregate = _aggregate_metrics(sample_results)
        gate_reasons = _gate_reasons(
            aggregate,
            minimum=manifest.quality_gate.minimum,
            maximum=manifest.quality_gate.maximum,
        )
        run_payload = {
            "schema_version": 1,
            "metric_schema_version": WORKBOOK_QUALITY_METRIC_SCHEMA_VERSION,
            "dataset_id": manifest.dataset_id,
            "dataset_version": manifest.dataset_version,
            "dataset_digest": manifest.dataset_digest,
            "split": manifest.split,
            "parser_version": __version__,
            "quality_gate": {
                "minimum": manifest.quality_gate.minimum,
                "maximum": manifest.quality_gate.maximum,
            },
            "artifact_options": {"markdown": markdown},
            "results": sample_results,
        }
        run_digest = _payload_digest(run_payload)
        summary = {
            "schema_version": 1,
            "metric_schema_version": WORKBOOK_QUALITY_METRIC_SCHEMA_VERSION,
            "dataset_id": manifest.dataset_id,
            "dataset_version": manifest.dataset_version,
            "dataset_digest": manifest.dataset_digest,
            "split": manifest.split,
            "parser_version": __version__,
            "sample_count": len(sample_results),
            "metrics": aggregate,
            "quality_gate": run_payload["quality_gate"],
            "artifact_options": run_payload["artifact_options"],
            "gate_reasons": gate_reasons,
            "status": "passed" if not gate_reasons else "failed",
            "run_digest": run_digest,
        }
        run_dir = output_root / run_digest.removeprefix("sha256:")
        _publish_report(run_dir, sample_results, summary, markdown=markdown)
        return WorkbookQualityBenchmarkReport(
            run_digest=run_digest,
            output_path=run_dir,
            summary=summary,
            results=tuple(sample_results),
        )


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, float | None]:
    aggregated: dict[str, float | None] = {}
    for metric_field in fields(WorkbookQualityMetrics):
        values = [
            result["metrics"][metric_field.name]
            for result in results
            if result["metrics"][metric_field.name] is not None
        ]
        aggregated[metric_field.name] = sum(values) / len(values) if values else None
    return aggregated


def _gate_reasons(
    metrics: dict[str, float | None],
    *,
    minimum: dict[str, float],
    maximum: dict[str, float],
) -> list[str]:
    reasons = []
    for name, threshold in sorted(minimum.items()):
        value = metrics.get(name)
        if value is None or value < threshold:
            reasons.append(f"{name}_below_minimum")
    for name, threshold in sorted(maximum.items()):
        value = metrics.get(name)
        if value is None or value > threshold:
            reasons.append(f"{name}_above_maximum")
    return reasons


def _payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _file_identity(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    return stat.st_size, stat.st_mtime_ns, digest


def _publish_report(
    run_dir: Path,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    markdown: bool,
) -> None:
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = run_dir.parent / f".{run_dir.name}.{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    try:
        results_text = "".join(
            json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n" for result in results
        )
        (temporary / "workbook-quality-results.jsonl").write_text(
            results_text,
            encoding="utf-8",
        )
        (temporary / "workbook-quality-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if markdown:
            (temporary / "workbook-quality-summary.md").write_text(
                _summary_markdown(summary),
                encoding="utf-8",
            )
        if run_dir.exists():
            if not _directories_equal(run_dir, temporary):
                raise WorkbookQualityReportError(
                    f"Immutable report collision for {summary['run_digest']}"
                )
            return
        os.replace(temporary, run_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _directories_equal(left: Path, right: Path) -> bool:
    left_files = {path.relative_to(left): path for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right): path for path in right.rglob("*") if path.is_file()}
    return left_files.keys() == right_files.keys() and all(
        left_files[name].read_bytes() == right_files[name].read_bytes() for name in left_files
    )


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Workbook Quality Summary ({summary['dataset_id']})",
        "",
        f"- **Dataset Version**: {summary['dataset_version']}",
        f"- **Dataset Digest**: {summary['dataset_digest']}",
        f"- **Split**: {summary['split']}",
        f"- **Parser Version**: {summary['parser_version']}",
        f"- **Metric Schema Version**: {summary['metric_schema_version']}",
        f"- **Status**: {summary['status']}",
        f"- **Run Digest**: {summary['run_digest']}",
        f"- **Gate Reasons**: {', '.join(summary['gate_reasons']) or 'none'}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in summary["metrics"].items())
    return "\n".join(lines) + "\n"
