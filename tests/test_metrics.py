from langparse.metrics import (
    BatchItemResult,
    BatchRunResult,
    ParseMetrics,
    collect_parse_metrics,
    count_markdown_tables,
    pages_per_second,
)
from langparse.types import Chunk, ParsedDocumentResult, ParsedPageResult


def _result(pages, **metadata):
    return ParsedDocumentResult(
        source="a.pdf",
        filename="a.pdf",
        engine="simple",
        pages=pages,
        markdown_content="\n".join(page.markdown_content for page in pages),
        metadata=metadata,
    )


def test_page_marker_coverage_is_full_when_every_page_is_numbered():
    parsed = _result(
        [
            ParsedPageResult(page_number=1, markdown_content="one"),
            ParsedPageResult(page_number=2, markdown_content="two"),
        ]
    )

    assert collect_parse_metrics(parsed, 1.0).page_marker_coverage == 1.0


def test_page_marker_coverage_reports_partial_when_a_page_is_unnumbered():
    parsed = _result(
        [
            ParsedPageResult(page_number=1, markdown_content="one"),
            ParsedPageResult(page_number=0, markdown_content="two"),
        ]
    )

    assert collect_parse_metrics(parsed, 1.0).page_marker_coverage == 0.5


def test_page_marker_coverage_is_zero_for_unpaginated_documents():
    parsed = _result([ParsedPageResult(page_number=1, markdown_content="one")])
    parsed.paginated = False

    assert collect_parse_metrics(parsed, 1.0).page_marker_coverage == 0.0


def test_collect_parse_metrics_counts_supplied_chunks():
    parsed = _result([ParsedPageResult(page_number=1, markdown_content="one")])
    chunks = [
        Chunk(content="a", metadata={"page_numbers": [1]}),
        Chunk(content="b", metadata={"page_numbers": []}),
        Chunk(content="c", metadata={}),
    ]

    metrics = collect_parse_metrics(parsed, 1.0, chunks=chunks)

    assert metrics.chunk_count == 3
    assert metrics.chunks_with_page_numbers_ratio == round(1 / 3, 4)


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
