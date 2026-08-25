from langparse.workbooks.continuation import score_continuation
from langparse.workbooks.types import (
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    SheetSnapshot,
    SourceRef,
    TableFragment,
)


def _table_fixture(
    sheet_name: str,
    sheet_index: int,
    *,
    headers: tuple[tuple[str, ...] | str, ...] = ("Item", "Value"),
    title: str = "清单",
    page: int | None = None,
    total_pages: int | None = None,
    last_role: str = "data",
    column_start: int = 1,
    widths: tuple[float | None, ...] | None = None,
    units: tuple[str | None, ...] | None = None,
    data_values: tuple[tuple[str, ...], ...] = (),
) -> tuple[SheetSnapshot, LogicalTable]:
    coordinates = tuple(chr(ord("A") + column_start - 1 + index) for index in range(len(headers)))
    source_ref = SourceRef(
        sheet_name=sheet_name,
        range=f"{coordinates[0]}1:{coordinates[-1]}5",
    )
    column_widths = {
        coordinate: width
        for coordinate, width in zip(coordinates, widths or (), strict=False)
        if width is not None
    }
    sheet = SheetSnapshot(
        name=sheet_name,
        index=sheet_index,
        column_widths=column_widths,
    )
    columns = [
        HeaderColumn(
            column_id=f"column_{index}",
            coordinate=coordinate,
            path=[header] if isinstance(header, str) else list(header),
            unit=(units or (None,) * len(headers))[index],
        )
        for index, (coordinate, header) in enumerate(zip(coordinates, headers, strict=True))
    ]
    rows = [
        LogicalRow(
            row_id=f"row_{index}",
            source_ref=source_ref,
            role="data",
            values=list(values),
        )
        for index, values in enumerate(data_values)
    ]
    rows.append(
        LogicalRow(
            row_id="last_row",
            source_ref=source_ref,
            role=last_role,
            values=[],
        )
    )
    fragment = TableFragment(
        fragment_id="fragment_1",
        source_ref=source_ref,
        page_number=page,
        total_pages=total_pages,
    )
    return sheet, LogicalTable(
        table_id=f"table_{sheet_index}",
        title=title,
        columns=columns,
        rows=rows,
        fragments=[fragment],
        source_refs=[source_ref],
    )


def test_score_accepts_matching_header_title_and_page_sequence():
    # Break caught: dropping any primary contextual signal must not lower a full continuation.
    left_sheet, left = _table_fixture("清单1", 0, page=1, total_pages=2)
    right_sheet, right = _table_fixture("清单2", 1, page=2, total_pages=2)

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 1.0
    assert candidate.terminal_reason_codes == ()
    assert set(candidate.reason_codes) >= {
        "header_fingerprint_match",
        "print_page_sequence",
        "title_match",
        "sheet_name_sequence",
    }


def test_score_returns_none_for_different_header_fingerprint():
    # Break caught: unrelated schemas must not become ambiguous continuation candidates.
    left_sheet, left = _table_fixture("清单1", 0, headers=("Name", "Value"))
    right_sheet, right = _table_fixture("清单2", 1, headers=("Code", "Amount"))

    assert score_continuation(left_sheet, left, right_sheet, right) is None


def test_score_marks_title_mismatch_and_terminal_total():
    # Break caught: positive signals must not hide an explicit total or a new business title.
    left_sheet, left = _table_fixture("清单1", 0, title="甲表", last_role="total")
    right_sheet, right = _table_fixture("清单2", 1, title="乙表")

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert set(candidate.terminal_reason_codes) == {"terminal_total", "title_mismatch"}


def test_score_normalizes_page_markers_and_continuation_title_suffixes():
    # Break caught: cosmetic page and continuation labels must not prevent title evidence.
    left_sheet, left = _table_fixture("Left", 0, title="清单 第１页 共２页")
    right_sheet, right = _table_fixture("Right", 1, title="清单（续表）")

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.6
    assert "title_match" in candidate.reason_codes
    assert candidate.terminal_reason_codes == ()


def test_score_marks_conflicting_page_metadata_as_terminal():
    # Break caught: incompatible print pages must block continuation despite other evidence.
    left_sheet, left = _table_fixture("清单1", 0, page=1, total_pages=2)
    right_sheet, right = _table_fixture("清单2", 1, page=3, total_pages=2)

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.85
    assert candidate.terminal_reason_codes == ("page_sequence_conflict",)


def test_score_marks_page_number_beyond_total_as_terminal():
    # Break caught: a numerically adjacent page outside the declared total is not a continuation.
    left_sheet, left = _table_fixture("清单1", 0, page=2, total_pages=2)
    right_sheet, right = _table_fixture("清单2", 1, page=3, total_pages=2)

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.85
    assert "print_page_sequence" not in candidate.reason_codes
    assert candidate.terminal_reason_codes == ("page_sequence_conflict",)


def test_score_recognizes_sequential_sheet_names():
    # Break caught: sheet-order context must be counted without title or page evidence.
    left_sheet, left = _table_fixture("Data1", 0, title="")
    right_sheet, right = _table_fixture("Data2", 1, title="")

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.6
    assert candidate.reason_codes == ("header_fingerprint_match", "sheet_name_sequence")


def test_score_uses_explicit_compatible_widths_at_shifted_table_positions():
    # Break caught: matching widths must compare paired table positions, not identical source letters.
    left_sheet, left = _table_fixture(
        "Left",
        0,
        title="",
        widths=(10.0, 20.0),
    )
    right_sheet, right = _table_fixture(
        "Right",
        1,
        title="",
        column_start=4,
        widths=(11.0, 18.0),
    )

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.5
    assert candidate.reason_codes == ("header_fingerprint_match", "column_width_compatibility")


def test_score_uses_unit_column_value_overlap_when_explicit_units_are_missing():
    # Break caught: stable unit values must contribute evidence even without HeaderColumn.unit.
    left_sheet, left = _table_fixture(
        "Left",
        0,
        title="",
        headers=("Item", "Unit"),
        data_values=(("first", "kg"), ("second", "m")),
    )
    right_sheet, right = _table_fixture(
        "Right",
        1,
        title="",
        headers=("Item", "Unit"),
        data_values=(("third", "kg"),),
    )

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.45
    assert candidate.reason_codes == ("header_fingerprint_match", "unit_compatibility")


def test_score_does_not_fallback_to_unit_values_when_an_explicit_unit_is_incomplete():
    # Break caught: one-sided explicit units must not be masked by coincident row values.
    left_sheet, left = _table_fixture(
        "Left",
        0,
        title="",
        headers=("Item", "Unit"),
        units=(None, "kg"),
        data_values=(("first", "kg"),),
    )
    right_sheet, right = _table_fixture(
        "Right",
        1,
        title="",
        headers=("Item", "Unit"),
        data_values=(("second", "kg"),),
    )

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.35
    assert candidate.reason_codes == ("header_fingerprint_match",)


def test_score_uses_positional_placeholders_for_empty_header_paths():
    # Break caught: shifted tables with matching blank header positions must retain schema compatibility.
    left_sheet, left = _table_fixture("Left", 0, title="", headers=((), "Value"))
    right_sheet, right = _table_fixture(
        "Right",
        1,
        title="",
        headers=((), "Value"),
        column_start=4,
    )

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.35
    assert candidate.reason_codes == ("header_fingerprint_match",)


def test_score_reports_title_only_candidate_at_ambiguous_threshold():
    # Break caught: header plus title evidence must remain visible at the 0.60 review threshold.
    left_sheet, left = _table_fixture("Left", 0)
    right_sheet, right = _table_fixture("Right", 1)

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 0.6
    assert candidate.reason_codes == ("header_fingerprint_match", "title_match")
