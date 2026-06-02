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
