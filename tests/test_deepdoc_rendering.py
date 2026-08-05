from langparse.engines.pdf.deepdoc.rendering import html_table_to_rows


def test_simple_table_without_spans():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_table_to_rows(html) == [["A", "B"], ["1", "2"]]


def test_colspan_header_repeats_value_across_columns():
    html = (
        "<table>"
        "<tr><th colspan='2'>Header</th></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Header", "Header"], ["1", "2"]]


def test_rowspan_first_column_repeats_value_down_rows():
    html = (
        "<table>"
        "<tr><td rowspan='2'>Group</td><td>1</td></tr>"
        "<tr><td>2</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Group", "1"], ["Group", "2"]]


def test_combined_colspan_and_rowspan():
    html = (
        "<table>"
        "<tr><td rowspan='2' colspan='2'>Merged</td><td>C</td></tr>"
        "<tr><td>D</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Merged", "Merged", "C"], ["Merged", "Merged", "D"]]


def test_whitespace_around_cell_text_is_stripped():
    html = "<table><tr><td>  padded  </td></tr></table>"
    assert html_table_to_rows(html) == [["padded"]]


def test_empty_table_returns_empty_list():
    assert html_table_to_rows("<table></table>") == []
