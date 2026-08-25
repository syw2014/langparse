from langparse.workbooks.regions import detect_candidate_regions
from langparse.workbooks.types import CellSnapshot, SheetSnapshot


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
