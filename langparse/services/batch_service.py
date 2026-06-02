from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from langparse.errors import classify_exception
from langparse.metrics import BatchItemResult, BatchRunResult, collect_parse_metrics
from langparse.services.parse_service import ParseService


class BatchParseService:
    def __init__(self, parse_service: ParseService | None = None):
        self.parse_service = parse_service or ParseService()

    def run(
        self,
        inputs,
        engine_name: str = "simple",
        output_dir="out",
        fmt: str = "markdown",
        max_workers: int | None = None,
        skip_existing: bool = False,
        fail_fast: bool = False,
        collect_metrics: bool = True,
        **kwargs,
    ) -> BatchRunResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = self.expand_inputs(inputs)
        worker_count = max_workers or min(4, os.cpu_count() or 1)

        if worker_count == 1:
            items = [
                self._run_one(
                    path,
                    output_dir,
                    engine_name,
                    fmt,
                    skip_existing,
                    fail_fast,
                    collect_metrics,
                    **kwargs,
                )
                for path in paths
            ]
        else:
            items = []
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        self._run_one,
                        path,
                        output_dir,
                        engine_name,
                        fmt,
                        skip_existing,
                        fail_fast,
                        collect_metrics,
                        **kwargs,
                    ): path
                    for path in paths
                }
                for future in as_completed(futures):
                    items.append(future.result())
            items.sort(key=lambda item: item.source)

        result = BatchRunResult(items=items, summary=self._build_summary(items))
        self._write_jsonl(output_dir / "batch-results.jsonl", items)
        self._write_json(output_dir / "batch-summary.json", result.summary)
        return result

    def expand_inputs(self, inputs) -> list[Path]:
        paths: list[Path] = []
        for item in self._flatten(inputs):
            path = Path(item)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            if path.is_dir():
                paths.extend(
                    sorted(
                        child
                        for child in path.iterdir()
                        if child.is_file() and child.suffix.lower() == ".pdf"
                    )
                )
            else:
                paths.append(path)
        return sorted(paths)

    def _run_one(
        self,
        path: Path,
        output_dir: Path,
        engine_name: str,
        fmt: str,
        skip_existing: bool,
        fail_fast: bool,
        collect_metrics: bool,
        **kwargs,
    ) -> BatchItemResult:
        started_at = self._utc_now()
        output_path = output_dir / self._output_filename(path, fmt)
        if skip_existing and output_path.exists():
            return BatchItemResult(
                source=str(path),
                status="skipped",
                output_path=str(output_path),
                engine=engine_name,
                started_at=started_at,
                finished_at=self._utc_now(),
            )

        start = time.perf_counter()
        try:
            parsed = self.parse_service.parse_result(path, engine_name=engine_name, **kwargs)
            rendered = self.parse_service.render_output(parsed, fmt)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            elapsed = time.perf_counter() - start
            metrics = collect_parse_metrics(parsed, elapsed) if collect_metrics else None
            return BatchItemResult(
                source=str(path),
                status="success",
                output_path=str(output_path),
                metrics=metrics,
                engine=engine_name,
                started_at=started_at,
                finished_at=self._utc_now(),
            )
        except Exception as exc:
            if fail_fast:
                raise
            classified = classify_exception(exc)
            return BatchItemResult(
                source=str(path),
                status="failed",
                engine=engine_name,
                error_type=classified.error_type.value,
                error_message=classified.message,
                started_at=started_at,
                finished_at=self._utc_now(),
            )

    def _build_summary(self, items: list[BatchItemResult]) -> dict:
        total_pages = sum((item.metrics.page_count if item.metrics else 0) for item in items)
        total_elapsed = sum((item.metrics.elapsed_seconds if item.metrics else 0.0) for item in items)
        return {
            "total_files": len(items),
            "success_count": sum(1 for item in items if item.status == "success"),
            "failed_count": sum(1 for item in items if item.status == "failed"),
            "skipped_count": sum(1 for item in items if item.status == "skipped"),
            "total_pages": total_pages,
            "total_elapsed_seconds": round(total_elapsed, 4),
            "average_pages_per_second": round(total_pages / total_elapsed, 4)
            if total_elapsed > 0
            else 0.0,
            "failed_sources": [item.source for item in items if item.status == "failed"],
        }

    def _output_filename(self, source: Path, fmt: str) -> str:
        return f"{source.stem}{'.md' if fmt == 'markdown' else '.json'}"

    def _write_jsonl(self, path: Path, items: list[BatchItemResult]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _flatten(self, inputs) -> Iterable:
        if isinstance(inputs, (str, Path)):
            yield inputs
            return
        for item in inputs:
            yield item

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
