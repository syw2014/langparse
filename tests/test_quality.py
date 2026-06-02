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
    checks = QualityCheck(
        min_pages=3,
        min_chars=1000,
        min_tables=1,
        min_images=1,
        require_page_markers=True,
    )

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
