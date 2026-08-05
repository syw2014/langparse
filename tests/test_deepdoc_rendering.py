from langparse.engines.pdf.deepdoc.rendering import html_table_to_rows, render_pages


def test_simple_table_without_spans():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_table_to_rows(html) == [["A", "B"], ["1", "2"]]


def test_colspan_header_repeats_value_across_columns():
    html = "<table><tr><th colspan='2'>Header</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_table_to_rows(html) == [["Header", "Header"], ["1", "2"]]


def test_rowspan_first_column_repeats_value_down_rows():
    html = "<table><tr><td rowspan='2'>Group</td><td>1</td></tr><tr><td>2</td></tr></table>"
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


def _box(page_number=1, layout_type="text", text="", **rect):
    return {
        "page_number": page_number,
        "layout_type": layout_type,
        "text": text,
        "x0": rect.get("x0", 0.0),
        "x1": rect.get("x1", 10.0),
        "top": rect.get("top", 0.0),
        "bottom": rect.get("bottom", 1.0),
    }


def test_title_box_becomes_markdown_heading():
    pages = render_pages([_box(layout_type="title", text="Chapter 1")])

    assert pages[0].markdown_content == "# Chapter 1"
    assert pages[0].elements[0].kind == "title"
    assert pages[0].elements[0].bbox == [0.0, 0.0, 10.0, 1.0]


def test_plain_text_box_is_kept_as_is():
    pages = render_pages([_box(layout_type="text", text="Body paragraph.")])

    assert pages[0].markdown_content == "Body paragraph."
    assert pages[0].plain_text == "Body paragraph."


def test_table_box_produces_rows_and_markdown_table():
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    pages = render_pages([_box(layout_type="table", text=html)])

    assert pages[0].tables == [{"rows": [["A"], ["1"]]}]
    assert "| A |" in pages[0].markdown_content
    assert pages[0].elements[0].kind == "table"


def test_figure_box_produces_an_image_entry_and_caption():
    pages = render_pages([_box(layout_type="figure", text="Figure 1: a chart")])

    assert pages[0].images == [{"caption": "Figure 1: a chart", "bbox": [0.0, 0.0, 10.0, 1.0]}]
    assert "Figure 1: a chart" in pages[0].markdown_content


def test_boxes_are_grouped_and_sorted_by_page_number():
    pages = render_pages(
        [
            _box(page_number=2, text="second"),
            _box(page_number=1, text="first"),
        ]
    )

    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].plain_text == "first"
    assert pages[1].plain_text == "second"


def test_blank_text_box_is_skipped():
    pages = render_pages([_box(layout_type="text", text="   ")])

    assert pages[0].markdown_content == ""
    assert pages[0].elements == []


def test_engine_name_is_stamped_on_page_metadata():
    pages = render_pages([_box(text="x")])

    assert pages[0].metadata["engine_name"] == "deepdoc"
