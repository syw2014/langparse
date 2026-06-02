# LangParse Product Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight product-ready parsing core for LangParse with batch runtime, benchmark reporting, PDF quality checks, and metrics for parsing quality and efficiency.

**Architecture:** Keep `ParseService` focused on single-file parsing and rendering. Add focused service modules for batch parsing, benchmark execution, quality checks, metrics, and error classification. MinerU remains the primary PDF engine, while SimplePDF provides a lightweight baseline with table extraction.

**Tech Stack:** Python 3.10+, dataclasses, argparse, pathlib, json/jsonl, concurrent.futures, pytest, existing LangParse parser and engine architecture.

---

## File Structure

### Create

- `langparse/errors.py`  
  Defines lightweight parse error categories and maps exceptions into stable error types for batch and benchmark results.

- `langparse/metrics.py`  
  Defines parse/batch/benchmark result dataclasses and helpers to measure elapsed time, output size, page count, pages per second, table count, image count, and chunk page coverage.

- `langparse/services/batch_service.py`  
  Implements `BatchParseService`, directory/list expansion, concurrent parsing, skip-existing behavior, fail-fast behavior, JSONL/summary writing, and item-level metrics.

- `langparse/services/quality.py`  
  Implements PDF-focused quality checks for tables, OCR, multi-column risk, header/footer filtering metadata, images/captions, page markers, and minimum output thresholds.

- `langparse/services/benchmark_service.py`  
  Implements manifest loading, sample execution, quality checks, benchmark JSONL/summary writing, and structured return values.

- `examples/benchmark_usage.py`  
  Minimal benchmark example using a manifest path and output directory.

- `samples/public.example.json`  
  Example manifest with representative PDF pain-point checks but no large PDF committed.

- `tests/test_metrics.py`
- `tests/test_errors.py`
- `tests/test_batch_service.py`
- `tests/test_quality.py`
- `tests/test_benchmark_service.py`

### Modify

- `langparse/types.py`  
  Re-export or host any result dataclasses if keeping all public dataclasses in one module is preferred.

- `langparse/services/parse_service.py`  
  Add `parse_result()` for callers that need `ParsedDocumentResult`; keep existing `parse_file()` compatibility.

- `langparse/services/__init__.py`  
  Export `ParseService`, `BatchParseService`, and `BenchmarkService`.

- `langparse/engines/pdf/simple.py`  
  Add basic `pdfplumber.extract_tables()` support and table metadata.

- `langparse/cli.py`  
  Add `parse --max-workers --skip-existing --metrics` and new `benchmark` subcommand.

- `README.md`
- `README_cn.md`
- `docs/INSTALL_TEST.md`
- `examples/README.md`
- `.gitignore`

---

## Task 1: Result Models and Error Classification

**Files:**
- Create: `langparse/errors.py`
- Create: `langparse/metrics.py`
- Modify: `langparse/__init__.py`
- Test: `tests/test_errors.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing error classification tests**

Create `tests/test_errors.py`:

```python
import pytest

from langparse.errors import ErrorType, classify_exception


def test_classify_file_not_found():
    error = classify_exception(FileNotFoundError("missing.pdf"))

    assert error.error_type == ErrorType.FILE_NOT_FOUND
    assert "missing.pdf" in error.message


def test_classify_dependency_missing_from_import_error():
    error = classify_exception(ImportError("Please install `pdfplumber`."))

    assert error.error_type == ErrorType.DEPENDENCY_MISSING
    assert "pdfplumber" in error.message


def test_classify_cuda_unavailable_as_engine_unavailable():
    error = classify_exception(RuntimeError("CUDA was requested for MinerU but is not available."))

    assert error.error_type == ErrorType.ENGINE_UNAVAILABLE
    assert "CUDA" in error.message


def test_classify_unknown_runtime_error_as_parse_failed():
    error = classify_exception(RuntimeError("unexpected parser crash"))

    assert error.error_type == ErrorType.PARSE_FAILED
    assert "unexpected parser crash" in error.message
```

- [ ] **Step 2: Write failing metrics model tests**

Create `tests/test_metrics.py`:

```python
from langparse.metrics import (
    BatchItemResult,
    BatchRunResult,
    ParseMetrics,
    count_markdown_tables,
    pages_per_second,
)


def test_pages_per_second_handles_zero_elapsed():
    assert pages_per_second(page_count=3, elapsed_seconds=0) == 0.0


def test_pages_per_second_rounds_to_four_decimals():
    assert pages_per_second(page_count=5, elapsed_seconds=2) == 2.5


def test_count_markdown_tables_counts_separator_rows():
    markdown = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n| X | Y |\n| --- | --- |\n| 3 | 4 |"

    assert count_markdown_tables(markdown) == 2


def test_batch_run_result_summary_counts_statuses():
    run = BatchRunResult(
        items=[
            BatchItemResult(source="a.pdf", status="success", metrics=ParseMetrics(page_count=2)),
            BatchItemResult(source="b.pdf", status="failed", error_type="parse_failed"),
            BatchItemResult(source="c.pdf", status="skipped"),
        ]
    )

    assert run.total_files == 3
    assert run.success_count == 1
    assert run.failed_count == 1
    assert run.skipped_count == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/test_errors.py tests/test_metrics.py -v
```

Expected: FAIL because `langparse.errors` and `langparse.metrics` do not exist.

- [ ] **Step 4: Implement `langparse/errors.py`**

Create `langparse/errors.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorType(str, Enum):
    DEPENDENCY_MISSING = "dependency_missing"
    FILE_NOT_FOUND = "file_not_found"
    UNSUPPORTED_FORMAT = "unsupported_format"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    ENGINE_TIMEOUT = "engine_timeout"
    PARSE_FAILED = "parse_failed"
    QUALITY_CHECK_FAILED = "quality_check_failed"
    OCR_UNAVAILABLE = "ocr_unavailable"
    LAYOUT_QUALITY_WARNING = "layout_quality_warning"
    TABLE_EXTRACTION_FAILED = "table_extraction_failed"


@dataclass
class ClassifiedError:
    error_type: ErrorType
    message: str


def classify_exception(exc: BaseException) -> ClassifiedError:
    message = str(exc)
    lowered = message.lower()

    if isinstance(exc, FileNotFoundError):
        return ClassifiedError(ErrorType.FILE_NOT_FOUND, message)
    if isinstance(exc, ImportError):
        return ClassifiedError(ErrorType.DEPENDENCY_MISSING, message)
    if "unsupported file extension" in lowered:
        return ClassifiedError(ErrorType.UNSUPPORTED_FORMAT, message)
    if "cuda" in lowered and "not available" in lowered:
        return ClassifiedError(ErrorType.ENGINE_UNAVAILABLE, message)
    if "unable to start local mineru-api" in lowered:
        return ClassifiedError(ErrorType.ENGINE_UNAVAILABLE, message)
    if "timed out" in lowered or "timeout" in lowered:
        return ClassifiedError(ErrorType.ENGINE_TIMEOUT, message)
    if "ocr" in lowered and "unavailable" in lowered:
        return ClassifiedError(ErrorType.OCR_UNAVAILABLE, message)
    if "table" in lowered and "failed" in lowered:
        return ClassifiedError(ErrorType.TABLE_EXTRACTION_FAILED, message)

    return ClassifiedError(ErrorType.PARSE_FAILED, message)
```

- [ ] **Step 5: Implement `langparse/metrics.py`**

Create `langparse/metrics.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def pages_per_second(page_count: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0
    return round(page_count / elapsed_seconds, 4)


def count_markdown_tables(markdown: str) -> int:
    separator_pattern = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    return sum(1 for line in markdown.splitlines() if separator_pattern.match(line))


@dataclass
class ParseMetrics:
    elapsed_seconds: float = 0.0
    page_count: int = 0
    pages_per_second: float = 0.0
    output_bytes: int = 0
    markdown_chars: int = 0
    table_count: int = 0
    image_count: int = 0
    chunk_count: int = 0
    chunks_with_page_numbers_ratio: float = 0.0
    page_marker_coverage: float = 0.0
    ocr_applied: bool = False
    ocr_text_chars: int = 0
    multi_column_detected: bool = False
    reading_order_warnings: int = 0
    header_footer_removed_count: int = 0
    caption_count: int = 0
    images_with_caption_ratio: float = 0.0


@dataclass
class BatchItemResult:
    source: str
    status: str
    output_path: str | None = None
    metrics: ParseMetrics | None = None
    error_type: str | None = None
    error_message: str | None = None
    engine: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class BatchRunResult:
    items: list[BatchItemResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def total_files(self) -> int:
        return len(self.items)

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.items if item.status == "skipped")
```

- [ ] **Step 6: Re-export public result classes**

Modify `langparse/__init__.py`:

```python
from langparse.metrics import BatchItemResult, BatchRunResult, ParseMetrics

__all__ = [
    "Document",
    "Chunk",
    "ParsedDocumentResult",
    "ParsedPageResult",
    "ParsedElement",
    "ParseMetrics",
    "BatchItemResult",
    "BatchRunResult",
    "BaseParser",
    "BaseChunker",
    "AutoParser",
    "PDFParser",
    "MarkdownParser",
    "DocxParser",
    "ExcelParser",
    "SemanticChunker",
]
```

Keep all existing imports in `__init__.py`; add only the new import and `__all__` entries.

- [ ] **Step 7: Run tests to verify task passes**

Run:

```bash
pytest tests/test_errors.py tests/test_metrics.py -v
pytest -q
```

Expected: PASS, including existing 54 tests.

- [ ] **Step 8: Commit**

```bash
git add langparse/errors.py langparse/metrics.py langparse/__init__.py tests/test_errors.py tests/test_metrics.py
git commit -m "feat: add parse metrics and error classification"
```

---

## Task 2: Single-File Parsed Result and Metrics Collection

**Files:**
- Modify: `langparse/services/parse_service.py`
- Modify: `langparse/metrics.py`
- Test: `tests/test_parse_service.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Add failing tests for `parse_result()` and metric collection**

Append to `tests/test_parse_service.py`:

```python
from langparse.metrics import collect_parse_metrics


def test_parse_result_returns_normalized_result(tmp_path):
    class FastPathEngine:
        def process_document(self, file_path, **kwargs):
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
                markdown_content="Hello",
                metadata={},
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    parsed = ParseService().parse_result(pdf, engine_name="simple", engine=FastPathEngine())

    assert parsed.engine == "simple"
    assert parsed.pages[0].markdown_content == "Hello"


def test_collect_parse_metrics_counts_pages_tables_and_output_size():
    parsed = ParsedDocumentResult(
        source="sample.pdf",
        filename="sample.pdf",
        engine="simple",
        pages=[
            ParsedPageResult(
                page_number=1,
                markdown_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
                tables=[{"rows": [["A", "B"], ["1", "2"]]}],
                images=[{"bbox": [0, 0, 10, 10]}],
            )
        ],
        markdown_content="| A | B |\n| --- | --- |\n| 1 | 2 |",
        metadata={"ocr_applied": True, "ocr_text_chars": 12},
    )

    metrics = collect_parse_metrics(parsed, elapsed_seconds=2)

    assert metrics.page_count == 1
    assert metrics.pages_per_second == 0.5
    assert metrics.table_count == 1
    assert metrics.image_count == 1
    assert metrics.ocr_applied is True
    assert metrics.ocr_text_chars == 12
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
pytest tests/test_parse_service.py::test_parse_result_returns_normalized_result tests/test_parse_service.py::test_collect_parse_metrics_counts_pages_tables_and_output_size -v
```

Expected: FAIL because `parse_result` and `collect_parse_metrics` are missing.

- [ ] **Step 3: Implement `collect_parse_metrics()`**

Append to `langparse/metrics.py`:

```python
from langparse.types import ParsedDocumentResult


def collect_parse_metrics(parsed: ParsedDocumentResult, elapsed_seconds: float) -> ParseMetrics:
    markdown = parsed.markdown_content or ""
    page_count = len(parsed.pages)
    image_count = sum(len(page.images) for page in parsed.pages)
    table_count = sum(len(page.tables) for page in parsed.pages) or count_markdown_tables(markdown)
    caption_count = sum(
        1
        for page in parsed.pages
        for image in page.images
        if image.get("caption")
    )

    return ParseMetrics(
        elapsed_seconds=round(elapsed_seconds, 4),
        page_count=page_count,
        pages_per_second=pages_per_second(page_count, elapsed_seconds),
        output_bytes=len(markdown.encode("utf-8")),
        markdown_chars=len(markdown),
        table_count=table_count,
        image_count=image_count,
        ocr_applied=bool(parsed.metadata.get("ocr_applied", False)),
        ocr_text_chars=int(parsed.metadata.get("ocr_text_chars", 0) or 0),
        multi_column_detected=bool(parsed.metadata.get("multi_column_detected", False)),
        reading_order_warnings=int(parsed.metadata.get("reading_order_warnings", 0) or 0),
        header_footer_removed_count=int(parsed.metadata.get("header_footer_removed_count", 0) or 0),
        caption_count=caption_count,
        images_with_caption_ratio=round(caption_count / image_count, 4) if image_count else 0.0,
    )
```

- [ ] **Step 4: Add `ParseService.parse_result()`**

Modify `langparse/services/parse_service.py`:

```python
    def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        return self._collect_pdf_document_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            **kwargs,
        )
```

Place it above `parse_file()`. Then update `parse_file()` to reuse it:

```python
    def parse_file(self, file_path, engine_name="simple", engine=None, **kwargs):
        parsed = self.parse_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            **kwargs,
        )
        return self._build_document_from_result(parsed)
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_parse_service.py tests/test_metrics.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add langparse/services/parse_service.py langparse/metrics.py tests/test_parse_service.py tests/test_metrics.py
git commit -m "feat: expose parsed results and metrics collection"
```

---

## Task 3: Batch Parse Service

**Files:**
- Create: `langparse/services/batch_service.py`
- Modify: `langparse/services/__init__.py`
- Test: `tests/test_batch_service.py`

- [ ] **Step 1: Write failing batch service tests**

Create `tests/test_batch_service.py`:

```python
from pathlib import Path

import pytest

from langparse.metrics import BatchRunResult
from langparse.services.batch_service import BatchParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


class StubParseService:
    def __init__(self):
        self.calls = []

    def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        self.calls.append((Path(file_path), engine_name, kwargs))
        return ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine=engine_name,
            pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
            markdown_content="Hello",
            metadata={},
        )

    def render_output(self, parsed, fmt):
        return parsed.markdown_content if fmt == "markdown" else "{}"


def test_batch_service_writes_outputs_and_summary(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"

    service = BatchParseService(parse_service=StubParseService())
    result = service.run([pdf], output_dir=output_dir, fmt="markdown", max_workers=1)

    assert isinstance(result, BatchRunResult)
    assert result.success_count == 1
    assert (output_dir / "a.md").read_text(encoding="utf-8") == "Hello"
    assert (output_dir / "batch-results.jsonl").exists()
    assert (output_dir / "batch-summary.json").exists()


def test_batch_service_skip_existing_marks_item_skipped(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "a.md").write_text("old", encoding="utf-8")

    parse_service = StubParseService()
    result = BatchParseService(parse_service=parse_service).run(
        [pdf],
        output_dir=output_dir,
        fmt="markdown",
        max_workers=1,
        skip_existing=True,
    )

    assert result.skipped_count == 1
    assert parse_service.calls == []


def test_batch_service_records_failure_when_fail_fast_false(tmp_path):
    class FailingParseService(StubParseService):
        def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
            raise RuntimeError("parser failed")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    result = BatchParseService(parse_service=FailingParseService()).run(
        [pdf],
        output_dir=tmp_path / "out",
        max_workers=1,
        fail_fast=False,
    )

    assert result.failed_count == 1
    assert result.items[0].error_type == "parse_failed"


def test_batch_service_raises_when_fail_fast_true(tmp_path):
    class FailingParseService(StubParseService):
        def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
            raise RuntimeError("parser failed")

    pdf = tmp_path / "a.pdf"
    pdf.write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError, match="parser failed"):
        BatchParseService(parse_service=FailingParseService()).run(
            [pdf],
            output_dir=tmp_path / "out",
            max_workers=1,
            fail_fast=True,
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_batch_service.py -v
```

Expected: FAIL because `langparse.services.batch_service` does not exist.

- [ ] **Step 3: Implement `BatchParseService`**

Create `langparse/services/batch_service.py`:

```python
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
        **kwargs,
    ) -> BatchRunResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = self.expand_inputs(inputs)
        worker_count = max_workers or min(4, os.cpu_count() or 1)

        if worker_count == 1:
            items = [
                self._run_one(path, output_dir, engine_name, fmt, skip_existing, fail_fast, **kwargs)
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
                        **kwargs,
                    ): path
                    for path in paths
                }
                for future in as_completed(futures):
                    if fail_fast:
                        items.append(future.result())
                    else:
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
                paths.extend(sorted(child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".pdf"))
            else:
                paths.append(path)
        return sorted(paths)

    def _run_one(self, path: Path, output_dir: Path, engine_name: str, fmt: str, skip_existing: bool, fail_fast: bool, **kwargs) -> BatchItemResult:
        started_at = self._utc_now()
        output_path = output_dir / self._output_filename(path, fmt)
        if skip_existing and output_path.exists():
            return BatchItemResult(source=str(path), status="skipped", output_path=str(output_path), engine=engine_name, started_at=started_at, finished_at=self._utc_now())

        start = time.perf_counter()
        try:
            parsed = self.parse_service.parse_result(path, engine_name=engine_name, **kwargs)
            rendered = self.parse_service.render_output(parsed, fmt)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            elapsed = time.perf_counter() - start
            metrics = collect_parse_metrics(parsed, elapsed)
            return BatchItemResult(source=str(path), status="success", output_path=str(output_path), metrics=metrics, engine=engine_name, started_at=started_at, finished_at=self._utc_now())
        except Exception as exc:
            if fail_fast:
                raise
            elapsed = time.perf_counter() - start
            classified = classify_exception(exc)
            return BatchItemResult(source=str(path), status="failed", engine=engine_name, error_type=classified.error_type.value, error_message=classified.message, started_at=started_at, finished_at=self._utc_now())

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
            "average_pages_per_second": round(total_pages / total_elapsed, 4) if total_elapsed > 0 else 0.0,
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
```

- [ ] **Step 4: Export service**

Modify `langparse/services/__init__.py`:

```python
from langparse.services.batch_service import BatchParseService
from langparse.services.parse_service import ParseService

__all__ = ["BatchParseService", "ParseService"]
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_batch_service.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add langparse/services/batch_service.py langparse/services/__init__.py tests/test_batch_service.py
git commit -m "feat: add lightweight batch parse service"
```

---

## Task 4: PDF Quality Checks

**Files:**
- Create: `langparse/services/quality.py`
- Test: `tests/test_quality.py`

- [ ] **Step 1: Write failing quality check tests**

Create `tests/test_quality.py`:

```python
from langparse.metrics import ParseMetrics
from langparse.services.quality import QualityCheck, run_quality_checks


def test_quality_checks_pass_when_thresholds_met():
    metrics = ParseMetrics(
        page_count=5,
        markdown_chars=4000,
        table_count=2,
        image_count=1,
        page_marker_coverage=1.0,
    )
    checks = QualityCheck(min_pages=3, min_chars=1000, min_tables=1, min_images=1, require_page_markers=True)

    result = run_quality_checks(metrics, checks)

    assert result.passed is True
    assert result.failures == []


def test_quality_checks_fail_for_missing_tables():
    metrics = ParseMetrics(page_count=5, markdown_chars=4000, table_count=0)
    checks = QualityCheck(min_tables=1, require_table_markdown=True)

    result = run_quality_checks(metrics, checks)

    assert result.passed is False
    assert "min_tables" in result.failures
    assert "require_table_markdown" in result.failures


def test_quality_checks_fail_for_scan_without_ocr_text():
    metrics = ParseMetrics(page_count=2, markdown_chars=0, ocr_applied=True, ocr_text_chars=0)
    checks = QualityCheck(require_ocr_text=True)

    result = run_quality_checks(metrics, checks)

    assert result.passed is False
    assert "require_ocr_text" in result.failures


def test_quality_checks_fail_for_multi_column_sample_without_layout_signal():
    metrics = ParseMetrics(multi_column_detected=False, reading_order_warnings=0)
    checks = QualityCheck(require_multi_column_check=True)

    result = run_quality_checks(metrics, checks)

    assert result.passed is False
    assert "require_multi_column_check" in result.failures
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_quality.py -v
```

Expected: FAIL because `langparse.services.quality` does not exist.

- [ ] **Step 3: Implement `quality.py`**

Create `langparse/services/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from langparse.metrics import ParseMetrics


@dataclass
class QualityCheck:
    min_pages: int | None = None
    min_chars: int | None = None
    min_tables: int | None = None
    min_images: int | None = None
    require_page_markers: bool = False
    require_table_markdown: bool = False
    require_ocr_text: bool = False
    require_multi_column_check: bool = False
    max_header_footer_repetition_ratio: float | None = None
    require_captions_for_images: bool = False


@dataclass
class QualityCheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_quality_checks(metrics: ParseMetrics, checks: QualityCheck) -> QualityCheckResult:
    failures: list[str] = []
    warnings: list[str] = []

    if checks.min_pages is not None and metrics.page_count < checks.min_pages:
        failures.append("min_pages")
    if checks.min_chars is not None and metrics.markdown_chars < checks.min_chars:
        failures.append("min_chars")
    if checks.min_tables is not None and metrics.table_count < checks.min_tables:
        failures.append("min_tables")
    if checks.min_images is not None and metrics.image_count < checks.min_images:
        failures.append("min_images")
    if checks.require_page_markers and metrics.page_marker_coverage <= 0:
        failures.append("require_page_markers")
    if checks.require_table_markdown and metrics.table_count <= 0:
        failures.append("require_table_markdown")
    if checks.require_ocr_text and metrics.ocr_text_chars <= 0:
        failures.append("require_ocr_text")
    if checks.require_multi_column_check and not metrics.multi_column_detected and metrics.reading_order_warnings == 0:
        failures.append("require_multi_column_check")
    if checks.require_captions_for_images and metrics.image_count > 0 and metrics.images_with_caption_ratio < 1.0:
        failures.append("require_captions_for_images")
    if checks.max_header_footer_repetition_ratio is not None and metrics.header_footer_removed_count == 0:
        warnings.append("header_footer_filter_not_applied")

    return QualityCheckResult(passed=not failures, failures=failures, warnings=warnings)
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_quality.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add langparse/services/quality.py tests/test_quality.py
git commit -m "feat: add pdf quality checks"
```

---

## Task 5: Benchmark Service and Manifest Reports

**Files:**
- Create: `langparse/services/benchmark_service.py`
- Modify: `langparse/services/__init__.py`
- Create: `samples/public.example.json`
- Modify: `.gitignore`
- Test: `tests/test_benchmark_service.py`

- [ ] **Step 1: Write failing benchmark tests**

Create `tests/test_benchmark_service.py`:

```python
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
                    metrics=ParseMetrics(page_count=2, markdown_chars=2000, table_count=1, page_marker_coverage=1.0),
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
                        "checks": {"min_pages": 1, "min_chars": 10, "min_tables": 1, "require_page_markers": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = BenchmarkService(batch_service=StubBatchService()).run(manifest, output_dir=tmp_path / "reports")

    assert result["summary"]["total_samples"] == 1
    assert result["summary"]["quality_passed_count"] == 1
    assert (tmp_path / "reports" / "benchmark-results.jsonl").exists()
    assert (tmp_path / "reports" / "benchmark-summary.json").exists()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_benchmark_service.py -v
```

Expected: FAIL because `langparse.services.benchmark_service` does not exist.

- [ ] **Step 3: Implement `BenchmarkService`**

Create `langparse/services/benchmark_service.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from langparse.services.batch_service import BatchParseService
from langparse.services.quality import QualityCheck, run_quality_checks


class BenchmarkService:
    def __init__(self, batch_service: BatchParseService | None = None):
        self.batch_service = batch_service or BatchParseService()

    def run(self, manifest_path, output_dir="reports", engine_name: str | None = None, fmt: str = "json", max_workers: int = 1, **kwargs) -> dict:
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
                quality = run_quality_checks(item.metrics, self._quality_check_from_dict(sample.get("checks", {})))
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
            "quality_failed_samples": [row["id"] for row in quality_rows if not row["quality"]["passed"]],
            "pdf_quality_summary": self._pdf_quality_summary(rows),
        }

    def _pdf_quality_summary(self, rows: list[dict]) -> dict:
        metrics = [row["metrics"] for row in rows if row["metrics"]]
        return {
            "total_tables": sum(item["table_count"] for item in metrics),
            "total_images": sum(item["image_count"] for item in metrics),
            "ocr_applied_count": sum(1 for item in metrics if item["ocr_applied"]),
            "reading_order_warning_count": sum(item["reading_order_warnings"] for item in metrics),
            "header_footer_removed_count": sum(item["header_footer_removed_count"] for item in metrics),
        }

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Export service**

Modify `langparse/services/__init__.py`:

```python
from langparse.services.batch_service import BatchParseService
from langparse.services.benchmark_service import BenchmarkService
from langparse.services.parse_service import ParseService

__all__ = ["BatchParseService", "BenchmarkService", "ParseService"]
```

- [ ] **Step 5: Add sample manifest and ignore private manifests**

Create `samples/public.example.json`:

```json
{
  "samples": [
    {
      "id": "public-pdf-quality-example",
      "path": "samples/public/public-pdf-quality-example.pdf",
      "category": "report",
      "features": ["tables", "multi_column", "figures", "headers_footers"],
      "engine": "mineru",
      "checks": {
        "min_pages": 1,
        "min_chars": 100,
        "min_tables": 1,
        "require_page_markers": true,
        "require_table_markdown": true,
        "require_multi_column_check": false,
        "require_captions_for_images": false
      }
    }
  ]
}
```

Append to `.gitignore`:

```gitignore
samples/*.local.json
samples/private/
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_benchmark_service.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add langparse/services/benchmark_service.py langparse/services/__init__.py samples/public.example.json .gitignore tests/test_benchmark_service.py
git commit -m "feat: add benchmark service and manifest reports"
```

---

## Task 6: CLI Batch Metrics and Benchmark Command

**Files:**
- Modify: `langparse/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_cli_parse_accepts_batch_metrics_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "parse",
            "docs/",
            "--batch",
            "--output-dir",
            "out",
            "--max-workers",
            "4",
            "--skip-existing",
            "--metrics",
        ]
    )

    assert args.max_workers == 4
    assert args.skip_existing is True
    assert args.metrics is True


def test_cli_benchmark_command_accepts_manifest_and_output_dir():
    parser = build_parser()
    args = parser.parse_args(
        [
            "benchmark",
            "samples/public.example.json",
            "--engine",
            "mineru",
            "--output-dir",
            "reports",
            "--max-workers",
            "2",
        ]
    )

    assert args.command == "benchmark"
    assert args.manifest == "samples/public.example.json"
    assert args.engine == "mineru"
    assert args.output_dir == "reports"
    assert args.max_workers == 2
```

- [ ] **Step 2: Write failing CLI delegation tests**

Append to `tests/test_cli.py`:

```python
def test_cli_main_batch_metrics_delegates_to_batch_service(monkeypatch):
    calls = []

    class FakeBatchService:
        def run(self, inputs, engine_name="simple", output_dir="out", fmt="markdown", max_workers=None, skip_existing=False, **kwargs):
            calls.append((inputs, engine_name, output_dir, fmt, max_workers, skip_existing, kwargs))
            return None

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)

    exit_code = main(
        [
            "parse",
            "docs/",
            "--batch",
            "--output-dir",
            "out",
            "--engine",
            "mineru",
            "--format",
            "json",
            "--max-workers",
            "4",
            "--skip-existing",
            "--metrics",
        ]
    )

    assert exit_code == 0
    assert calls == [(["docs/"], "mineru", "out", "json", 4, True, {"collect_metrics": True})]


def test_cli_main_benchmark_delegates_to_benchmark_service(monkeypatch):
    calls = []

    class FakeBenchmarkService:
        def run(self, manifest, output_dir="reports", engine_name=None, fmt="json", max_workers=1, **kwargs):
            calls.append((manifest, output_dir, engine_name, fmt, max_workers, kwargs))
            return {"summary": {"total_samples": 1}}

    monkeypatch.setattr("langparse.cli.BenchmarkService", FakeBenchmarkService)

    exit_code = main(
        [
            "benchmark",
            "samples/public.example.json",
            "--engine",
            "mineru",
            "--output-dir",
            "reports",
            "--max-workers",
            "2",
        ]
    )

    assert exit_code == 0
    assert calls == [("samples/public.example.json", "reports", "mineru", "json", 2, {})]
```

- [ ] **Step 3: Run CLI tests to verify failure**

Run:

```bash
pytest tests/test_cli.py -v
```

Expected: FAIL because CLI does not have these arguments or service imports.

- [ ] **Step 4: Update CLI imports and parser**

Modify imports in `langparse/cli.py`:

```python
from langparse.services.batch_service import BatchParseService
from langparse.services.benchmark_service import BenchmarkService
from langparse.services.parse_service import ParseService
```

Add parse options:

```python
    parse_cmd.add_argument("--max-workers", type=int, default=None)
    parse_cmd.add_argument("--skip-existing", action="store_true")
    parse_cmd.add_argument("--metrics", action="store_true")
```

Add benchmark subcommand in `build_parser()`:

```python
    benchmark_cmd = subparsers.add_parser("benchmark")
    benchmark_cmd.add_argument("manifest")
    benchmark_cmd.add_argument("--engine", default=None)
    benchmark_cmd.add_argument("--output-dir", default="reports")
    benchmark_cmd.add_argument("--format", default="json")
    benchmark_cmd.add_argument("--max-workers", type=int, default=1)
    benchmark_cmd.add_argument("--api-url", default=None)
    benchmark_cmd.add_argument("--device", default=None)
    benchmark_cmd.add_argument("--model-dir", default=None)
    benchmark_cmd.add_argument("--download-dir", default=None)
```

- [ ] **Step 5: Route parse batch to `BatchParseService` when metrics or new batch options are used**

In `main()`, replace the current `if args.batch:` block with:

```python
    if args.batch:
        if args.metrics or args.max_workers is not None or args.skip_existing:
            BatchParseService().run(
                args.inputs,
                engine_name=engine_name,
                output_dir=args.output_dir or "out",
                fmt=args.format,
                max_workers=args.max_workers,
                skip_existing=args.skip_existing,
                collect_metrics=args.metrics,
                **parse_kwargs,
            )
            return 0

        outputs = service.parse_batch_outputs(
            args.inputs,
            engine_name=engine_name,
            fmt=args.format,
            **parse_kwargs,
        )
        if args.output_dir:
            service.write_batch_outputs(outputs, args.output_dir, args.format)
        else:
            for _, rendered in outputs:
                print(rendered)
        return 0
```

- [ ] **Step 6: Route benchmark subcommand**

Before the parse command handling in `main()`, add:

```python
    if args.command == "benchmark":
        benchmark_kwargs = {
            key: value
            for key, value in {
                "api_url": args.api_url,
                "device": args.device,
                "model_dir": args.model_dir,
                "download_dir": args.download_dir,
            }.items()
            if value is not None
        }
        BenchmarkService().run(
            args.manifest,
            output_dir=args.output_dir,
            engine_name=args.engine,
            fmt=args.format,
            max_workers=args.max_workers,
            **benchmark_kwargs,
        )
        return 0
```

Keep `parse` behavior unchanged for existing tests.

- [ ] **Step 7: Run tests**

Run:

```bash
pytest tests/test_cli.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add langparse/cli.py tests/test_cli.py
git commit -m "feat: add cli batch metrics and benchmark command"
```

---

## Task 7: PDF Quality Baseline Improvements

**Files:**
- Modify: `langparse/engines/pdf/simple.py`
- Modify: `langparse/metrics.py`
- Test: `tests/test_mineru_engine.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Add failing SimplePDF table extraction test**

Append to `tests/test_pdf_parser.py`:

```python
def test_simple_pdf_engine_extracts_tables(monkeypatch, tmp_path):
    from langparse.engines.pdf.simple import SimplePDFEngine

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class StubPage:
        def extract_text(self):
            return "Report"

        def extract_tables(self):
            return [[["A", "B"], ["1", "2"]]]

    class StubPDF:
        pages = [StubPage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("pdfplumber.open", lambda path: StubPDF())

    page = next(SimplePDFEngine().process(pdf_path))

    assert page.tables == [{"rows": [["A", "B"], ["1", "2"]]}]
    assert "| A | B |" in page.markdown_content
```

- [ ] **Step 2: Add failing MinerU metadata metric test**

Append to `tests/test_mineru_engine.py`:

```python
def test_process_document_preserves_pdf_quality_metadata(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(device="cpu")
    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)
    monkeypatch.setattr(
        engine,
        "_run_mineru",
        lambda path, runtime_config: [
            {
                "page_number": 1,
                "markdown": "# Title",
                "images": [{"bbox": [0, 0, 10, 10], "caption": "Figure 1"}],
                "tables": [{"rows": [["A"], ["1"]]}],
                "engine_specific": {
                    "ocr_applied": True,
                    "ocr_text_chars": 10,
                    "multi_column_detected": True,
                    "reading_order_warnings": 1,
                    "header_footer_removed_count": 2,
                },
            }
        ],
    )

    parsed = engine.process_document(pdf_path)

    assert parsed.metadata["ocr_applied"] is True
    assert parsed.metadata["ocr_text_chars"] == 10
    assert parsed.metadata["multi_column_detected"] is True
    assert parsed.metadata["reading_order_warnings"] == 1
    assert parsed.metadata["header_footer_removed_count"] == 2
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_pdf_parser.py::test_simple_pdf_engine_extracts_tables tests/test_mineru_engine.py::test_process_document_preserves_pdf_quality_metadata -v
```

Expected: FAIL because table extraction and MinerU quality metadata aggregation are missing.

- [ ] **Step 4: Implement SimplePDF table extraction**

Modify `langparse/engines/pdf/simple.py` inside the page loop:

```python
                tables = []
                table_markdown = []
                for table in page.extract_tables() or []:
                    cleaned_table = [
                        ["" if cell is None else str(cell).strip().replace("\n", " ") for cell in row]
                        for row in table
                    ]
                    if not cleaned_table:
                        continue
                    tables.append({"rows": cleaned_table})
                    headers = cleaned_table[0]
                    table_markdown.append(f"| {' | '.join(headers)} |")
                    table_markdown.append(f"| {' | '.join(['---'] * len(headers))} |")
                    for row in cleaned_table[1:]:
                        table_markdown.append(f"| {' | '.join(row)} |")

                markdown_content = text
                if table_markdown:
                    markdown_content = "\n\n".join([text, "\n".join(table_markdown)]).strip()
```

Then update `PageResult`:

```python
                    markdown_content=markdown_content,
                    tables=tables,
```

- [ ] **Step 5: Aggregate MinerU quality metadata**

Modify `langparse/engines/pdf/mineru.py` before returning `ParsedDocumentResult`:

```python
        engine_specific_items = [page.metadata.get("engine_specific", {}) for page in pages]
        quality_metadata = {
            "ocr_applied": any(bool(item.get("ocr_applied")) for item in engine_specific_items),
            "ocr_text_chars": sum(int(item.get("ocr_text_chars", 0) or 0) for item in engine_specific_items),
            "multi_column_detected": any(bool(item.get("multi_column_detected")) for item in engine_specific_items),
            "reading_order_warnings": sum(int(item.get("reading_order_warnings", 0) or 0) for item in engine_specific_items),
            "header_footer_removed_count": sum(int(item.get("header_footer_removed_count", 0) or 0) for item in engine_specific_items),
        }
```

Update `ParsedDocumentResult.metadata`:

```python
            metadata={
                "device": runtime_config["device"],
                "model_dir": runtime_config["model_dir"],
                "download_dir": runtime_config["download_dir"],
                "enable_ocr": runtime_config["enable_ocr"],
                "model_policy": self.model_policy,
                "model_source": self.model_source,
                **quality_metadata,
            },
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_pdf_parser.py tests/test_mineru_engine.py tests/test_metrics.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add langparse/engines/pdf/simple.py langparse/engines/pdf/mineru.py tests/test_pdf_parser.py tests/test_mineru_engine.py
git commit -m "feat: add pdf quality metadata and simple table extraction"
```

---

## Task 8: Documentation and Examples

**Files:**
- Create: `examples/benchmark_usage.py`
- Modify: `examples/README.md`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `docs/INSTALL_TEST.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add benchmark example**

Create `examples/benchmark_usage.py`:

```python
from pathlib import Path

from langparse.services.benchmark_service import BenchmarkService


def main():
    manifest = Path("samples/public.example.json")
    output_dir = Path("reports/example-benchmark")
    result = BenchmarkService().run(manifest, output_dir=output_dir, engine_name="mineru")

    print("Benchmark summary:")
    print(result["summary"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update examples README**

Add to `examples/README.md`:

```markdown
## Benchmark example

- `benchmark_usage.py`: run a PDF quality benchmark from a manifest and write JSONL/summary reports.

```bash
python examples/benchmark_usage.py
```
```

- [ ] **Step 3: Update README CLI section**

Add to `README.md` under CLI examples:

```markdown
Run a product-readiness benchmark:

```bash
langparse benchmark samples/public.example.json --engine mineru --output-dir reports --max-workers 2
```

Benchmark reports include success rate, elapsed time, pages per second, table counts, OCR indicators, reading-order warnings, header/footer filtering counts, and image/caption metadata coverage.
```

- [ ] **Step 4: Update Chinese README**

Replace the outdated MinerU placeholder paragraph in `README_cn.md` with:

```markdown
LangParse 现在可以通过 `mineru-api` 调用 MinerU。你可以传入 `api_url` 连接已有服务，也可以省略 `api_url` 让 LangParse 尝试启动本地 `mineru-api` 并在当前解析任务结束后关闭。

第一阶段产品化重点是 PDF 解析质量和 RAG 可用性：表格 Markdown、页码引用、多列布局风险、OCR 指标、页眉页脚过滤统计、图像/图表 metadata，以及批量解析耗时和页数/秒。
```

- [ ] **Step 5: Update install test doc**

Replace the outdated MinerU placeholder paragraph in `docs/INSTALL_TEST.md` with:

```markdown
MinerU 支持两种运行方式：

- 远程或已有本地服务：传入 `api_url`
- 本地托管服务：省略 `api_url`，LangParse 会尝试启动 `mineru-api`

批量解析和 benchmark 会记录耗时、页数/秒、成功率、失败原因，以及 PDF 质量专项指标。
```

- [ ] **Step 6: Run docs-adjacent verification**

Run:

```bash
pytest tests/test_cli.py -v
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add examples/benchmark_usage.py examples/README.md README.md README_cn.md docs/INSTALL_TEST.md
git commit -m "docs: add benchmark and pdf quality guidance"
```

---

## Final Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI help smoke checks**

```bash
python -m langparse.cli --help
python -m langparse.cli parse --help
python -m langparse.cli benchmark --help
```

Expected: all commands print help and exit with code 0.

- [ ] **Step 3: Run benchmark with an intentionally missing public sample**

```bash
python -m langparse.cli benchmark samples/public.example.json --engine mineru --output-dir /tmp/langparse-benchmark-smoke
```

Expected: if the example PDF is absent, the command records file-not-found in benchmark output or raises a clear `FileNotFoundError`. It must not produce a silent success with empty output.

- [ ] **Step 4: Inspect git status**

```bash
git status --short
```

Expected: clean working tree after all commits.
