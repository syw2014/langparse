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
from langparse.parsers.registry import is_supported
from langparse.services.output_paths import resolve_output_paths
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
        chunk: bool = False,
        **kwargs,
    ) -> BatchRunResult:
        # No output directory means render to memory and let the caller print;
        # this is the same code path, not a second implementation.
        output_dir = Path(output_dir) if output_dir is not None else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        paths = self.expand_inputs(inputs)
        worker_count = max_workers or min(4, os.cpu_count() or 1)

        # Resolved up front, single-threaded: collision handling relies on shared
        # state and every worker needs a destination nobody else will claim.
        output_paths = [
            output_dir / relative if output_dir is not None else None
            for relative in resolve_output_paths(paths, fmt)
        ]

        engine = self.parse_service.create_engine(engine_name, **kwargs)

        job_args = [
            (
                path,
                output_path,
                engine_name,
                engine,
                fmt,
                skip_existing,
                fail_fast,
                collect_metrics,
                chunk,
            )
            for path, output_path in zip(paths, output_paths)
        ]

        if worker_count == 1:
            results = [self._run_one(*args, **kwargs) for args in job_args]
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(self._run_one, *args, **kwargs) for args in job_args
                ]
                # Indexed rather than as_completed: input order is what pairs
                # rendered output with the source the caller asked for.
                results = [future.result() for future in futures]

        items = [item for item, _ in results]
        result = BatchRunResult(
            items=items,
            summary=self._build_summary(items),
            rendered_outputs=[text for _, text in results if text is not None],
        )
        if output_dir is not None:
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
                        if child.is_file() and is_supported(child)
                    )
                )
            else:
                paths.append(path)
        return sorted(paths)

    def _run_one(
        self,
        path: Path,
        output_path: Path | None,
        engine_name: str,
        engine,
        fmt: str,
        skip_existing: bool,
        fail_fast: bool,
        collect_metrics: bool,
        chunk: bool,
        **kwargs,
    ) -> tuple[BatchItemResult, str | None]:
        """Return the report item and, when nothing was written, the rendered text."""
        started_at = self._utc_now()
        if skip_existing and output_path is not None and output_path.exists():
            return (
                BatchItemResult(
                    source=str(path),
                    status="skipped",
                    output_path=str(output_path),
                    engine=engine_name,
                    started_at=started_at,
                    finished_at=self._utc_now(),
                ),
                None,
            )

        start = time.perf_counter()
        try:
            parsed = self.parse_service.parse_result(
                path, engine_name=engine_name, engine=engine, **kwargs
            )
            chunks = self.parse_service.chunk_result(parsed) if chunk else None
            rendered = self.parse_service.render_output(parsed, fmt, chunks=chunks)
            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(rendered, encoding="utf-8")
            elapsed = time.perf_counter() - start
            metrics = (
                collect_parse_metrics(parsed, elapsed, chunks=chunks) if collect_metrics else None
            )
            return (
                BatchItemResult(
                    source=str(path),
                    status="success",
                    output_path=str(output_path) if output_path is not None else None,
                    metrics=metrics,
                    engine=engine_name,
                    started_at=started_at,
                    finished_at=self._utc_now(),
                ),
                None if output_path is not None else rendered,
            )
        except Exception as exc:
            if fail_fast:
                raise
            classified = classify_exception(exc)
            return self._failed_item(path, engine_name, classified, started_at), None

    def _failed_item(self, path, engine_name, classified, started_at) -> BatchItemResult:
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
