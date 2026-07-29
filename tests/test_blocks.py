from langparse.chunkers.blocks import scan_blocks


def kinds(markdown):
    return [block.kind for block in scan_blocks(markdown)]


def test_heading_is_recognised_with_level_and_title():
    blocks = scan_blocks("## Section title\n")

    assert blocks[0].kind == "heading"
    assert blocks[0].level == 2
    assert blocks[0].title == "Section title"


def test_hash_inside_a_fenced_code_block_is_not_a_heading():
    markdown = "# Real heading\n\n```python\n# just a comment\nx = 1\n```\n"

    blocks = scan_blocks(markdown)

    assert [block.kind for block in blocks] == ["heading", "code"]
    assert "# just a comment" in blocks[1].text


def test_tilde_fences_are_supported():
    markdown = "~~~\n# not a heading\n~~~\n"

    assert kinds(markdown) == ["code"]


def test_pipe_lines_inside_a_fence_are_not_a_table():
    markdown = "```\n| A | B |\n| --- | --- |\n```\n"

    assert kinds(markdown) == ["code"]


def test_table_needs_a_separator_row():
    table = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    not_a_table = "| just | pipes |\n| more | pipes |\n"

    assert kinds(table) == ["table"]
    assert kinds(not_a_table) == ["paragraph"]


def test_table_block_exposes_rows_and_header():
    blocks = scan_blocks("| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n")

    assert blocks[0].rows == [["A", "B"], ["1", "2"], ["3", "4"]]
    assert blocks[0].has_header is True


def test_page_marker_becomes_its_own_block_with_a_number():
    blocks = scan_blocks("<!-- page_number: 7 -->\nBody\n")

    assert blocks[0].kind == "page_marker"
    assert blocks[0].page_number == 7
    assert blocks[1].kind == "paragraph"


def test_blank_lines_separate_paragraphs():
    assert kinds("One.\n\nTwo.\n") == ["paragraph", "paragraph"]


def test_unclosed_fence_still_yields_a_code_block():
    assert kinds("```\nnever closed\n") == ["code"]


def test_empty_input_yields_no_blocks():
    assert scan_blocks("") == []
