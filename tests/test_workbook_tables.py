import pytest
from openpyxl.utils import get_column_letter

from langparse.workbooks.tables import interpret_logical_table
from langparse.workbooks.types import CandidateRegion, CellSnapshot, SheetSnapshot, SourceRef


def _put_row(sheet: SheetSnapshot, row_number: int, values: list[object | None]) -> None:
    for column_number, value in enumerate(values, start=1):
        if value is None:
            continue
        coordinate = f"{get_column_letter(column_number)}{row_number}"
        sheet.cells[coordinate] = CellSnapshot(
            coordinate=coordinate,
            raw_value=value,
            display_value=str(value),
        )


def _two_fragment_sheet() -> tuple[SheetSnapshot, CandidateRegion]:
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:L12")
    header_1 = [
        "序号",
        "项目编码",
        "项目名称",
        "项目特征描述",
        "计量单位",
        "工程量",
        "综合单价(元)",
        "合价(元)",
        "其中",
        None,
        None,
        "备注",
    ]
    header_2 = [None, None, None, None, None, None, None, None, "人工费", "机械费", "管理费", None]
    for offset, page_number in ((0, 1), (6, 2)):
        _put_row(sheet, 1 + offset, ["表1-2 清单"])
        _put_row(
            sheet,
            2 + offset,
            [
                "单位工程名称",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                f"第 {page_number} 页 共 2 页",
            ],
        )
        _put_row(sheet, 3 + offset, header_1)
        _put_row(sheet, 4 + offset, header_2)
        _put_row(sheet, 5 + offset, [1 + offset, "code", "item"])
        _put_row(sheet, 6 + offset, [2 + offset, "code", "item"])
        for column in range(1, 9):
            anchor = f"{get_column_letter(column)}{3 + offset}"
            subordinate = f"{get_column_letter(column)}{4 + offset}"
            sheet.cells[subordinate] = CellSnapshot(
                coordinate=subordinate,
                merge_anchor=anchor,
            )
        for column in (10, 11):
            coordinate = f"{get_column_letter(column)}{3 + offset}"
            sheet.cells[coordinate] = CellSnapshot(
                coordinate=coordinate,
                merge_anchor=f"I{3 + offset}",
            )
        sheet.cells[f"L{4 + offset}"] = CellSnapshot(
            coordinate=f"L{4 + offset}",
            merge_anchor=f"L{3 + offset}",
        )
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name="Data", range="A1:L12"),
        cell_refs=list(sheet.cells),
    )
    return sheet, candidate


def test_detects_repeated_print_fragments():
    sheet, candidate = _two_fragment_sheet()

    table = interpret_logical_table(sheet, candidate)

    assert [fragment.page_number for fragment in table.fragments] == [1, 2]
    assert [fragment.source_ref.range for fragment in table.fragments] == ["A1:L6", "A7:L12"]
    assert table.fragments[1].header_row_numbers == [9, 10]
    assert table.title == "表1-2 清单"


def test_preserves_single_print_marker_for_cross_sheet_evidence():
    sheet = SheetSnapshot(name="清单1", index=0, used_range="A1:B4")
    _put_row(sheet, 1, ["工程清单"])
    _put_row(sheet, 2, ["第 1 页 共 2 页"])
    _put_row(sheet, 3, ["Name", "Value"])
    _put_row(sheet, 4, ["Alpha", 1])
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name=sheet.name, range="A1:B4"),
        cell_refs=list(sheet.cells),
    )

    table = interpret_logical_table(sheet, candidate)

    assert len(table.fragments) == 1
    assert table.fragments[0].page_number == 1
    assert table.fragments[0].total_pages == 2
    assert table.fragments[0].title_row_numbers == [1]
    assert table.fragments[0].context_row_numbers == [2]
    assert table.fragments[0].header_row_numbers == [3]
    assert [column.path for column in table.columns] == [["Name"], ["Value"]]
    assert table.title == "工程清单"


def test_requires_explicit_title_ownership_before_exposing_table_title():
    # Break caught: a generic header row must not also become continuation title evidence.
    sheet = SheetSnapshot(name="Data1", index=0, used_range="A1:B2")
    _put_row(sheet, 1, ["Name", "Value"])
    _put_row(sheet, 2, ["Alpha", 1])
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name=sheet.name, range="A1:B2"),
        cell_refs=list(sheet.cells),
    )

    table = interpret_logical_table(sheet, candidate)

    assert table.fragments[0].title_row_numbers == []
    assert [row.role for row in table.rows] == ["header", "data"]
    assert table.title == ""


def test_builds_multi_row_header_paths_from_merges():
    sheet, candidate = _two_fragment_sheet()

    table = interpret_logical_table(sheet, candidate)
    paths = {column.coordinate: column.path for column in table.columns}

    assert paths["A"] == ["序号"]
    assert paths["I"] == ["其中", "人工费"]
    assert paths["J"] == ["其中", "机械费"]
    assert paths["K"] == ["其中", "管理费"]


@pytest.mark.parametrize("page_marker", [False, True])
def test_separates_title_and_multiple_context_rows_from_headers(page_marker):
    sheet = SheetSnapshot(name="Summary", index=0, used_range="A1:C5")
    _put_row(sheet, 1, ["工程费用汇总表"])
    _put_row(sheet, 2, ["工程名称：示例工程"])
    _put_row(
        sheet, 3, ["单位工程名称：室外工程", None, "第 1 页 共 1 页" if page_marker else "单位：元"]
    )
    _put_row(sheet, 4, ["序号", "项目", "金额"])
    _put_row(sheet, 5, ["2.2", "技术措施", 125])
    candidate = CandidateRegion(source_ref=SourceRef(sheet_name=sheet.name, range="A1:C5"))

    table = interpret_logical_table(sheet, candidate)

    assert table.title == "工程费用汇总表"
    assert table.fragments[0].context_row_numbers == [2, 3]
    assert [column.path for column in table.columns] == [["序号"], ["项目"], ["金额"]]
    assert [row.role for row in table.rows] == ["title", "context", "context", "header", "data"]


def test_keeps_merged_parent_header_without_context_evidence():
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:B3")
    _put_row(sheet, 1, ["费用"])
    sheet.cells["B1"] = CellSnapshot(coordinate="B1", merge_anchor="A1")
    _put_row(sheet, 2, ["材料", "人工"])
    _put_row(sheet, 3, [120, 80])
    candidate = CandidateRegion(source_ref=SourceRef(sheet_name=sheet.name, range="A1:B3"))

    table = interpret_logical_table(sheet, candidate)

    assert table.title == ""
    assert [column.path for column in table.columns] == [["费用", "材料"], ["费用", "人工"]]


def test_native_table_header_labels_take_precedence_over_context_heuristics():
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:B2")
    _put_row(sheet, 1, ["项目名称：编号", "单位：元"])
    _put_row(sheet, 2, [1, 125])
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name=sheet.name, range="A1:B2"),
        reason_codes=["native_table_anchor"],
    )

    table = interpret_logical_table(sheet, candidate)

    assert [column.path for column in table.columns] == [["项目名称：编号"], ["单位：元"]]
    assert [row.role for row in table.rows] == ["header", "data"]


@pytest.mark.parametrize("identifier", ["2.1", "2.2", "1.2.3"])
def test_hierarchical_first_body_row_is_data_even_without_amount(identifier):
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:C2")
    _put_row(sheet, 1, ["序号", "项目", "金额"])
    _put_row(sheet, 2, [identifier, "措施项目", None])
    candidate = CandidateRegion(source_ref=SourceRef(sheet_name=sheet.name, range="A1:C2"))

    table = interpret_logical_table(sheet, candidate)

    assert table.fragments[0].header_row_numbers == [1]
    assert table.rows[1].role == "data"


def test_classifies_budget_row_roles_and_sections():
    sheet, candidate = _two_fragment_sheet()
    _put_row(sheet, 5, [0, 0, "土方", 0, 0, 0, 0, 4974])
    _put_row(sheet, 6, [1, "040101", "挖沟槽土方"])
    _put_row(sheet, 11, [2, "040103", "回填方"])
    _put_row(sheet, 12, ["合   计", None, None, None, None, None, None, 525891])

    table = interpret_logical_table(sheet, candidate)
    roles_by_row = {row.metadata["row_number"]: row.role for row in table.rows}

    assert roles_by_row == {
        1: "title",
        2: "context",
        3: "header",
        4: "header",
        5: "section_header",
        6: "data",
        7: "repeated_title",
        8: "repeated_context",
        9: "repeated_header",
        10: "repeated_header",
        11: "data",
        12: "total",
    }
    assert [section.title for section in table.sections] == ["土方"]
    assert next(row for row in table.rows if row.metadata["row_number"] == 11).section_path == [
        "土方"
    ]
    assert len({row.source_ref.key for row in table.rows}) == 12
