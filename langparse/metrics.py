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
