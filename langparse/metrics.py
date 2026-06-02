from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langparse.types import ParsedDocumentResult


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
