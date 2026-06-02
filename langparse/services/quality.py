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
    if (
        checks.require_multi_column_check
        and not metrics.multi_column_detected
        and metrics.reading_order_warnings == 0
    ):
        failures.append("require_multi_column_check")
    if (
        checks.require_captions_for_images
        and metrics.image_count > 0
        and metrics.images_with_caption_ratio < 1.0
    ):
        failures.append("require_captions_for_images")
    if checks.max_header_footer_repetition_ratio is not None and metrics.header_footer_removed_count == 0:
        warnings.append("header_footer_filter_not_applied")

    return QualityCheckResult(passed=not failures, failures=failures, warnings=warnings)
