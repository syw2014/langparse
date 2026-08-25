from openpyxl.utils import get_column_letter

from langparse.workbooks.assembly import assemble_baseline, assemble_workbook
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


def test_semantic_renderer_deduplicates_print_fragments_and_preserves_snapshot():
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:D11")

    def put_row(row_number: int, values: list[object | None]) -> None:
        for column_number, value in enumerate(values, start=1):
            if value is None:
                continue
            coordinate = f"{get_column_letter(column_number)}{row_number}"
            sheet.cells[coordinate] = CellSnapshot(
                coordinate=coordinate,
                raw_value=value,
                display_value=str(value),
            )

    put_row(1, ["清单"])
    put_row(2, ["单位工程", "第 1 页 共 2 页"])
    put_row(3, ["序号", "名称", "说明", "金额"])
    put_row(4, [0, "土方", "", 100])
    put_row(5, [1, "挖土", "", 40])
    put_row(6, ["清单"])
    put_row(7, ["单位工程", "第 2 页 共 2 页"])
    put_row(8, ["序号", "名称", "说明", "金额"])
    put_row(9, [2, "回填", "", 60])
    put_row(10, ["合计", "", "", 100])
    snapshot = WorkbookSnapshot(source="book.xlsx", filename="book.xlsx", sheets=[sheet])
    ir, _ = assemble_workbook(snapshot)

    markdown = render_workbook_markdown(snapshot, ir)

    assert markdown.count("### Table: 清单") == 1
    assert markdown.count("| 序号 | 名称 | 说明 | 金额 |") == 1
    assert "#### Section: 土方" in markdown
    assert "第 2 页 共 2 页" not in markdown
    assert "合计" in markdown
    assert ir.snapshot is snapshot
    assert ir.snapshot.sheets[0].cells["A6"].display_value == "清单"
