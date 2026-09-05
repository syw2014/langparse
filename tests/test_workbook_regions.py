from langparse.workbooks.regions import detect_candidate_regions
from langparse.workbooks.types import CellSnapshot, RegionAnchor, SheetSnapshot, SourceRef


def _sheet_with_values(values: dict[str, object]) -> SheetSnapshot:
    return SheetSnapshot(
        name="Data",
        index=0,
        cells={
            coordinate: CellSnapshot(
                coordinate=coordinate,
                raw_value=value,
                display_value=str(value),
            )
            for coordinate, value in values.items()
        },
    )


def test_blank_rows_split_vertical_tables():
    sheet = _sheet_with_values({"A1": "H1", "A2": 1, "A5": "H2", "A6": 2})

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:A2", "A5:A6"]


def test_blank_columns_split_horizontal_tables():
    sheet = _sheet_with_values({"A1": "H1", "A2": 1, "D1": "H2", "D2": 2})

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:A2", "D1:D2"]


def test_merged_subordinates_keep_a_region_connected():
    sheet = _sheet_with_values({"A1": "Title", "A2": "Value", "B2": 1})
    sheet.cells["B1"] = CellSnapshot(coordinate="B1", merge_anchor="A1")

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2"]
    assert regions[0].cell_refs == ["A1", "B1", "A2", "B2"]


def test_empty_sheet_has_no_candidate_regions():
    assert detect_candidate_regions(SheetSnapshot(name="Empty", index=0)) == []


def test_native_table_anchors_split_adjacent_tables_without_blank_column():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "C1": "Item",
            "D1": "Amount",
            "A2": "Alpha",
            "B2": 1,
            "C2": "Beta",
            "D2": 2,
        }
    )
    sheet.region_anchors = [
        RegionAnchor("excel_table", SourceRef("Data", "A1:B2"), "LeftTable"),
        RegionAnchor("excel_table", SourceRef("Data", "C1:D2"), "RightTable"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "C1:D2"]
    assert all("native_table_anchor" in region.reason_codes for region in regions)
    assert all(region.confidence >= 0.95 for region in regions)


def test_native_table_boundaries_do_not_split_an_adjacent_taller_table():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "C1": "Item",
            "D1": "Amount",
            "A2": "Alpha",
            "B2": 1,
            "A3": "Beta",
            "B3": 2,
            "C2": "First",
            "D2": 10,
            "C3": "Second",
            "D3": 20,
            "C4": "Third",
            "D4": 30,
            "C5": "Fourth",
            "D5": 40,
        }
    )
    sheet.region_anchors = [
        RegionAnchor("excel_table", SourceRef("Data", "A1:B3"), "ShortTable"),
        RegionAnchor("excel_table", SourceRef("Data", "C1:D5"), "TallTable"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D5"]
    assert all(region.reason_codes == ["native_table_anchor"] for region in regions)


def test_shared_merged_title_is_not_split_by_native_table_boundaries():
    sheet = _sheet_with_values(
        {
            "A1": "Quarterly overview",
            "A2": "Name",
            "B2": "Value",
            "C2": "Item",
            "D2": "Amount",
            "A3": "Alpha",
            "B3": 1,
            "C3": "First",
            "D3": 10,
            "A4": "Beta",
            "B4": 2,
            "C4": "Second",
            "D4": 20,
        }
    )
    sheet.merged_ranges = ["A1:D1"]
    sheet.cells["A1"].colspan = 4
    for coordinate in ("B1", "C1", "D1"):
        sheet.cells[coordinate] = CellSnapshot(
            coordinate=coordinate,
            merge_anchor="A1",
        )
    sheet.region_anchors = [
        RegionAnchor("excel_table", SourceRef("Data", "A2:B4"), "LeftTable"),
        RegionAnchor("excel_table", SourceRef("Data", "C2:D4"), "RightTable"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == [
        "A1:D1",
        "A2:B4",
        "C2:D4",
    ]
    assert regions[0].reason_codes == ["merged_title_anchor"]
    assert all(region.reason_codes == ["native_table_anchor"] for region in regions[1:])


def test_native_anchors_partition_an_inverse_t_layout():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 7)}
    )
    sheet.region_anchors = [
        RegionAnchor("excel_table", SourceRef("Data", "A1:B6"), "TallLeft"),
        RegionAnchor("excel_table", SourceRef("Data", "C1:D3"), "TopRight"),
        RegionAnchor("excel_table", SourceRef("Data", "C4:D6"), "BottomRight"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == [
        "A1:B6",
        "C1:D3",
        "C4:D6",
    ]
    assert all(region.reason_codes == ["native_table_anchor"] for region in regions)


def test_native_table_anchor_bridges_an_internal_blank_row():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "A2": "Alpha",
            "B2": 1,
            "A4": "Beta",
            "B4": 2,
        }
    )
    sheet.region_anchors = [RegionAnchor("excel_table", SourceRef("Data", "A1:B4"), "SparseTable")]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B4"]
    assert regions[0].reason_codes == ["native_table_anchor"]
    assert regions[0].cell_refs == ["A1", "B1", "A2", "B2", "A4", "B4"]


def test_style_boundary_splits_two_dense_adjacent_regions():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 4)}
    )
    for coordinate, cell in sheet.cells.items():
        cell.style_id = "left" if coordinate[0] in "AB" else "right"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D3"]
    assert all("style_boundary" in region.reason_codes for region in regions)


def test_style_boundary_detects_default_to_filled_transition():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 4)}
    )
    for coordinate, cell in sheet.cells.items():
        if coordinate[0] in "CD":
            cell.visual_style_id = "filled"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D3"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def test_style_boundary_splits_two_dense_vertically_adjacent_regions():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "A2": "Alpha",
            "B2": 10,
            "A3": "Item",
            "B3": "Amount",
            "A4": "Beta",
            "B4": 20,
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "top" if int(coordinate[1:]) <= 2 else "bottom"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "A3:B4"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def test_two_same_style_header_rows_do_not_split_from_table_body():
    sheet = _sheet_with_values(
        {
            "A1": "Category",
            "B1": "Metrics",
            "A2": "Item",
            "B2": "Amount",
            "A3": "Alpha",
            "B3": 10,
            "A4": "Beta",
            "B4": 20,
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "header" if int(coordinate[1:]) <= 2 else "body"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B4"]
    assert regions[0].reason_codes == ["occupied_extent"]


def test_row_style_boundary_splits_adjacent_text_only_tables():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Status",
            "A2": "Alpha",
            "B2": "Open",
            "A3": "Item",
            "B3": "Owner",
            "A4": "Task",
            "B4": "Alice",
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "top" if int(coordinate[1:]) <= 2 else "bottom"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "A3:B4"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def test_row_style_changes_inside_one_table_do_not_create_regions():
    sheet = _sheet_with_values(
        {
            "A1": "Quarterly report",
            "B1": "Quarterly report",
            "A2": "Item",
            "B2": "Amount",
            "A3": "Alpha",
            "B3": 10,
            "A4": "Beta",
            "B4": 20,
        }
    )
    for coordinate, cell in sheet.cells.items():
        row = int(coordinate[1:])
        cell.visual_style_id = "title" if row == 1 else "header" if row == 2 else "body"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B4"]
    assert regions[0].reason_codes == ["occupied_extent"]


def test_formula_reference_vetoes_horizontal_visual_style_split():
    sheet = _sheet_with_values(
        {
            "A1": "Item",
            "B1": "Amount",
            "A2": "Alpha",
            "B2": 10,
            "A3": "=A2",
            "B3": "=B2*2",
            "A4": "=A3",
            "B4": "=B3*2",
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "top" if int(coordinate[1:]) <= 2 else "bottom"
        if int(coordinate[1:]) >= 3:
            cell.formula = str(cell.raw_value)

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B4"]
    assert regions[0].reason_codes == ["formula_continuity", "occupied_extent"]


def test_density_boundary_detaches_long_form_note():
    sheet = _sheet_with_values(
        {
            "A1": "项目名称",
            "B1": "道路工程",
            "A2": "建设单位",
            "B2": "示例公司",
            "A3": "负责人",
            "B3": "张三",
            "C1": "本段是紧邻表单但不属于字段值的较长说明文字",
        }
    )

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:C3"]
    assert all("density_boundary" in region.reason_codes for region in regions)


def test_row_density_boundary_detaches_long_note_below_a_form():
    sheet = _sheet_with_values(
        {
            "A1": "项目名称",
            "B1": "道路工程",
            "A2": "建设单位",
            "B2": "示例公司",
            "A3": "负责人",
            "B3": "张三",
            "A4": "本段是紧邻表单但不属于字段值的较长说明文字",
        }
    )

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "A4:B4"]
    assert all(region.reason_codes == ["density_boundary"] for region in regions)


def test_formula_reference_vetoes_visual_style_split():
    sheet = _sheet_with_values(
        {
            "A1": "Item",
            "B1": "Rate",
            "C1": "Amount",
            "D1": "Tax",
            "A2": "Alpha",
            "B2": 2,
            "C2": "=B2*2",
            "D2": "=C2*0.1",
            "A3": "Beta",
            "B3": 3,
            "C3": "=B3*2",
            "D3": "=C3*0.1",
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.style_id = "input" if coordinate[0] in "AB" else "output"
        if coordinate in {"C2", "C3", "D2", "D3"}:
            cell.formula = str(cell.raw_value)

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:D3"]
    assert regions[0].reason_codes == ["formula_continuity", "occupied_extent"]


def test_cross_sheet_formula_does_not_veto_a_local_style_boundary():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "C1": "Item",
            "D1": "Amount",
            "A2": "Alpha",
            "B2": 1,
            "C2": "First",
            "D2": "='Rates'!A1",
            "A3": "Beta",
            "B3": 2,
            "C3": "Second",
            "D3": "='Rates'!A2",
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "left" if coordinate[0] in "AB" else "right"
        if coordinate in {"D2", "D3"}:
            cell.formula = str(cell.raw_value)

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D3"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def test_formula_string_literal_does_not_veto_a_style_boundary():
    sheet = _styled_formula_sheet('="A1"', '="A2"')

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D3"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def test_cell_like_sheet_name_does_not_count_as_a_local_formula_reference():
    sheet = _styled_formula_sheet("='A1'!B2", "='A1'!B3")

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B3", "C1:D3"]
    assert all(region.reason_codes == ["style_boundary"] for region in regions)


def _styled_formula_sheet(first_formula: str, second_formula: str) -> SheetSnapshot:
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "C1": "Item",
            "D1": "Amount",
            "A2": "Alpha",
            "B2": 1,
            "C2": "First",
            "D2": first_formula,
            "A3": "Beta",
            "B3": 2,
            "C3": "Second",
            "D3": second_formula,
        }
    )
    for coordinate, cell in sheet.cells.items():
        cell.visual_style_id = "left" if coordinate[0] in "AB" else "right"
        if coordinate in {"D2", "D3"}:
            cell.formula = str(cell.raw_value)
    return sheet


def test_multiple_print_areas_split_adjacent_print_regions():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 3)}
    )
    sheet.print_area = ["Data!$A$1:$B$2", "Data!$C$1:$D$2"]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "C1:D2"]
    assert all("print_area_anchor" in region.reason_codes for region in regions)


def test_conflicting_native_anchors_keep_non_overlapping_cell_ownership():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 3)}
    )
    sheet.region_anchors = [
        RegionAnchor("excel_table", SourceRef("Data", "A1:C2"), "Table1"),
        RegionAnchor("defined_name", SourceRef("Data", "B1:D2"), "Overlap"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:C2", "D1:D2"]
    flattened = [coordinate for region in regions for coordinate in region.cell_refs]
    assert sorted(flattened) == sorted(sheet.cells)
    assert len(flattened) == len(set(flattened))
    assert any(
        diagnostic["reason_code"] == "overlapping_native_anchors"
        for region in regions
        for diagnostic in region.diagnostics
    )
    conflict = next(
        diagnostic
        for region in regions
        for diagnostic in region.diagnostics
        if diagnostic["reason_code"] == "overlapping_native_anchors"
    )
    assert conflict["kept_name"] == "Table1"
    assert conflict["kept_scope"] == "workbook"
    assert conflict["rejected_name"] == "Overlap"
    assert conflict["rejected_scope"] == "workbook"


def test_same_range_named_anchors_are_deduplicated_without_a_conflict():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "A2": "Alpha",
            "B2": 1,
        }
    )
    sheet.region_anchors = [
        RegionAnchor("defined_name", SourceRef("Data", "A1:B2"), "FirstName"),
        RegionAnchor("defined_name", SourceRef("Data", "A1:B2"), "SecondName"),
    ]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2"]
    assert regions[0].reason_codes == ["defined_name_anchor"]
    assert regions[0].confidence == 0.95
    assert regions[0].diagnostics == []


def test_style_only_empty_cells_remain_non_assignable_in_blank_separator():
    sheet = _sheet_with_values(
        {
            "A1": "Name",
            "B1": "Value",
            "A2": "Alpha",
            "B2": 1,
            "D1": "Item",
            "E1": "Amount",
            "D2": "Beta",
            "E2": 2,
        }
    )
    sheet.cells["C1"] = CellSnapshot(coordinate="C1", style_id="separator")

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "D1:E2"]
    assert all("blank_band" in region.reason_codes for region in regions)
    assert all("C1" not in region.cell_refs for region in regions)


def test_merged_title_vetoes_style_cut_across_its_span():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 4)}
    )
    sheet.merged_ranges = ["A1:D1"]
    sheet.cells["A1"].colspan = 4
    for coordinate, cell in sheet.cells.items():
        cell.style_id = "left" if coordinate[0] in "AB" else "right"

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:D3"]
    assert "merged_title_anchor" in regions[0].reason_codes


def test_usable_defined_name_splits_an_adjacent_region():
    sheet = _sheet_with_values(
        {f"{column}{row}": f"{column}{row}" for column in "ABCD" for row in range(1, 3)}
    )
    sheet.region_anchors = [RegionAnchor("defined_name", SourceRef("Data", "A1:B2"), "Inputs")]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2", "C1:D2"]
    assert "defined_name_anchor" in regions[0].reason_codes


def test_unbounded_region_anchor_is_ignored_without_breaking_detection():
    sheet = _sheet_with_values({"A1": "Name", "B1": "Value", "A2": "Alpha", "B2": 1})
    sheet.region_anchors = [RegionAnchor("defined_name", SourceRef("Data", "A:A"), "WholeColumn")]

    regions = detect_candidate_regions(sheet)

    assert [region.source_ref.range for region in regions] == ["A1:B2"]
    assert regions[0].reason_codes == ["occupied_extent"]
