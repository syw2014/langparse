from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


def test_renderer_uses_coordinates_not_unnamed_headers():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Cover",
                index=0,
                used_range="A1:C2",
                cells={
                    "A1": CellSnapshot(coordinate="A1", raw_value="Title", display_value="Title"),
                    "C2": CellSnapshot(coordinate="C2", raw_value=3, display_value="3"),
                },
            )
        ],
    )
    ir, _ = assemble_baseline(snapshot)

    markdown = render_workbook_markdown(snapshot, ir)

    assert "## Sheet: Cover" in markdown
    assert "<!-- source_range: Cover!A1:C2 -->" in markdown
    assert "| A | B | C |" in markdown
    assert "Unnamed:" not in markdown

    pages = compatibility_pages(snapshot, ir)
    assert pages[0].metadata == {
        "part_kind": "sheet",
        "sheet_name": "Cover",
        "source_range": "A1:C2",
    }
    assert pages[0].tables[0]["rows"][0] == ["A", "B", "C"]
    assert pages[0].tables[0]["rows"][1:] == [["Title", "", ""], ["", "", "3"]]
    assert pages[0].tables[0]["row_numbers"] == [1, 2]


def test_renderer_escapes_markdown_and_leaves_merged_subordinates_empty():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                used_range="B3:C3",
                cells={
                    "B3": CellSnapshot(
                        coordinate="B3",
                        raw_value="A|B\nC",
                        display_value="A|B\nC",
                        colspan=2,
                    ),
                    "C3": CellSnapshot(coordinate="C3", merge_anchor="B3"),
                },
            )
        ],
    )
    ir, _ = assemble_baseline(snapshot)

    markdown = render_workbook_markdown(snapshot, ir)

    assert "| A\\|B<br>C |  |" in markdown


def test_empty_sheet_is_preserved_without_a_fake_table():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[SheetSnapshot(name="Empty", index=0)],
    )
    ir, _ = assemble_baseline(snapshot)

    pages = compatibility_pages(snapshot, ir)

    assert len(pages) == 1
    assert pages[0].tables == []
    assert "## Sheet: Empty" in pages[0].markdown_content
