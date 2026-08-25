from langparse.workbooks.continuation import link_table_continuations, score_continuation
from langparse.workbooks.types import (
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    TableFragment,
    TableSection,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
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


def _workbook_ir(
    pairs: list[tuple[SheetSnapshot, list[LogicalTable]]],
) -> tuple[WorkbookSnapshot, WorkbookIR]:
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[sheet for sheet, _ in pairs],
    )
    ir = WorkbookIR(
        kind="workbook",
        workbook_id="workbook_1",
        source=snapshot.source,
        sheets=[
            SheetIR(
                sheet_id=f"sheet_{sheet.index}",
                name=sheet.name,
                index=sheet.index,
                blocks=[
                    WorkbookBlock(
                        block_id=f"block_{table.table_id}",
                        kind="logical_table",
                        source_refs=list(table.source_refs),
                        logical_table=table,
                    )
                    for table in tables
                ],
            )
            for sheet, tables in pairs
        ],
    )
    return snapshot, ir


def _member_tables(ir: WorkbookIR) -> list[LogicalTable]:
    return [
        block.logical_table
        for sheet in ir.sheets
        for block in sheet.blocks
        if block.logical_table is not None
    ]


def _three_sheet_ir() -> tuple[WorkbookSnapshot, WorkbookIR]:
    pairs = []
    for index, value in enumerate(("Alpha", "Beta", "Gamma"), start=1):
        sheet, table = _table_fixture(
            f"清单{index}",
            index - 1,
            page=index,
            total_pages=3,
            last_role="unknown",
            data_values=((value, str(index)),),
        )
        table.table_id = f"table_{index}"
        pairs.append((sheet, [table]))
    return _workbook_ir(pairs)


def _competing_ir() -> tuple[WorkbookSnapshot, WorkbookIR]:
    left_sheet, left_table = _table_fixture("清单1", 0, page=1, total_pages=2, last_role="unknown")
    left_table.table_id = "table_left"
    right_sheet, first_right = _table_fixture(
        "清单2", 1, page=2, total_pages=2, last_role="unknown"
    )
    first_right.table_id = "table_right_one"
    _, second_right = _table_fixture(
        "清单2", 1, page=2, total_pages=2, last_role="unknown", column_start=4
    )
    second_right.table_id = "table_right_two"
    return _workbook_ir([(left_sheet, [left_table]), (right_sheet, [first_right, second_right])])


def _presentation_table(
    sheet_name: str,
    sheet_index: int,
    *,
    page: int,
    data_rows: list[tuple[str, list[str]]],
    section: TableSection | None = None,
) -> tuple[SheetSnapshot, LogicalTable]:
    sheet, table = _table_fixture(
        sheet_name,
        sheet_index,
        page=page,
        total_pages=2,
        last_role="unknown",
    )
    source_ref = table.source_refs[0]
    for column in table.columns:
        column.source_refs = [SourceRef(sheet_name=sheet_name, range=f"{column.coordinate}3")]
    table.rows = [
        LogicalRow(
            row_id=f"{table.table_id}_title",
            source_ref=source_ref,
            role="title",
            values=["清单"],
        ),
        LogicalRow(
            row_id=f"{table.table_id}_context",
            source_ref=source_ref,
            role="context",
            values=[f"第 {page} 页"],
        ),
        LogicalRow(
            row_id=f"{table.table_id}_header",
            source_ref=source_ref,
            role="header",
            values=["Item", "Value"],
        ),
    ]
    for row_id, values in data_rows:
        table.rows.append(
            LogicalRow(
                row_id=row_id,
                source_ref=source_ref,
                role="data",
                values=values,
                section_path=[section.title] if section is not None else [],
            )
        )
    if section is not None:
        section.row_ids = [row_id for row_id, _ in data_rows]
        table.sections = [section]
    return sheet, table


def test_links_three_adjacent_tables_into_one_ordered_aggregate():
    # Break caught: losing the middle edge must split one three-Sheet continuation chain.
    snapshot, ir = _three_sheet_ir()

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert len(groups) == 1
    group = groups[0]
    assert group.member_table_ids == ["table_1", "table_2", "table_3"]
    assert group.reason_codes == [
        "header_fingerprint_match",
        "print_page_sequence",
        "title_match",
        "sheet_name_sequence",
    ]
    assert [table.continuation_role for table in _member_tables(ir)] == [
        "head",
        "member",
        "tail",
    ]
    assert [row.values[0] for row in group.logical_table.rows if row.role == "data"] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]
    assert {item["status"] for item in diagnostics} == {"accepted"}


def test_keeps_close_one_to_many_candidates_ambiguous():
    # Break caught: a tie must not arbitrarily pick one of two equally likely continuations.
    snapshot, ir = _competing_ir()

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert groups == []
    assert all(item["status"] == "ambiguous" for item in diagnostics)
    assert all("competing_continuation_candidates" in item["reason_codes"] for item in diagnostics)


def test_keeps_title_only_candidate_at_review_threshold_ambiguous():
    # Break caught: a 0.60 candidate must not cross the 0.85 automatic-link threshold.
    left_sheet, left = _table_fixture("Left", 0, last_role="unknown")
    right_sheet, right = _table_fixture("Right", 1, last_role="unknown")
    snapshot, ir = _workbook_ir([(left_sheet, [left]), (right_sheet, [right])])

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert groups == []
    assert diagnostics == [
        {
            "left_table_id": "table_0",
            "right_table_id": "table_1",
            "left_sheet": "Left",
            "right_sheet": "Right",
            "confidence": 0.6,
            "status": "ambiguous",
            "reason_codes": [
                "header_fingerprint_match",
                "title_match",
                "below_auto_accept_threshold",
            ],
        }
    ]


def test_rejects_terminal_candidate_with_a_complete_diagnostic_record():
    # Break caught: an explicit total must block a high-scoring automatic continuation.
    left_sheet, left = _table_fixture("清单1", 0, page=1, total_pages=2, last_role="total")
    right_sheet, right = _table_fixture("清单2", 1, page=2, total_pages=2)
    snapshot, ir = _workbook_ir([(left_sheet, [left]), (right_sheet, [right])])

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert groups == []
    assert diagnostics == [
        {
            "left_table_id": "table_0",
            "right_table_id": "table_1",
            "left_sheet": "清单1",
            "right_sheet": "清单2",
            "confidence": 1.0,
            "status": "rejected",
            "reason_codes": [
                "header_fingerprint_match",
                "print_page_sequence",
                "title_match",
                "sheet_name_sequence",
                "terminal_total",
            ],
        }
    ]


def test_skips_sheets_that_are_not_adjacent_by_index():
    # Break caught: list position must not make Sheet indexes 0 and 2 eligible for linking.
    left_sheet, left = _table_fixture("清单1", 0, page=1, total_pages=2, last_role="unknown")
    right_sheet, right = _table_fixture("清单2", 2, page=2, total_pages=2, last_role="unknown")
    snapshot, ir = _workbook_ir([(left_sheet, [left]), (right_sheet, [right])])

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert groups == []
    assert diagnostics == []


def test_accepts_only_a_mutual_unique_best_edge():
    # Break caught: a lower-scoring table on either endpoint must not steal an accepted link.
    left_sheet, best_left = _table_fixture("清单1", 0, page=1, total_pages=2, last_role="unknown")
    best_left.table_id = "table_best_left"
    _, other_left = _table_fixture("清单1", 0, last_role="unknown", column_start=4)
    other_left.table_id = "table_other_left"
    right_sheet, right = _table_fixture("清单2", 1, page=2, total_pages=2, last_role="unknown")
    right.table_id = "table_right"
    snapshot, ir = _workbook_ir([(left_sheet, [best_left, other_left]), (right_sheet, [right])])

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert [group.member_table_ids for group in groups] == [["table_best_left", "table_right"]]
    assert [best_left.continuation_role, right.continuation_role] == ["head", "tail"]
    assert other_left.continuation_id is None
    assert diagnostics[0]["status"] == "accepted"
    assert diagnostics[0]["left_table_id"] == "table_best_left"
    assert diagnostics[1]["status"] == "ambiguous"


def test_accepts_a_unique_best_with_an_exact_tenth_score_lead():
    # Break caught: binary float rounding must not turn the inclusive 0.10 lead into a tie.
    left_sheet, left = _table_fixture(
        "清单1",
        0,
        last_role="unknown",
        units=(None, "kg"),
    )
    left.table_id = "table_left"
    right_sheet, matching_unit = _table_fixture(
        "清单2",
        1,
        last_role="unknown",
        units=(None, "kg"),
    )
    matching_unit.table_id = "table_matching_unit"
    _, different_unit = _table_fixture(
        "清单2",
        1,
        last_role="unknown",
        units=(None, "m"),
        column_start=4,
    )
    different_unit.table_id = "table_different_unit"
    snapshot, ir = _workbook_ir(
        [(left_sheet, [left]), (right_sheet, [matching_unit, different_unit])]
    )

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert [group.member_table_ids for group in groups] == [["table_left", "table_matching_unit"]]
    assert [item["status"] for item in diagnostics] == ["accepted", "ambiguous"]
    assert "competing_continuation_candidates" not in diagnostics[0]["reason_codes"]


def test_aggregate_uses_copies_and_carries_a_section_path_across_members():
    # Break caught: aggregate-only relabeling or section inheritance must not alter source members.
    first_section = TableSection(
        section_id="section_a",
        title="Section A",
        source_ref=SourceRef(sheet_name="清单1", range="A4:B4"),
    )
    first_sheet, first = _presentation_table(
        "清单1",
        0,
        page=1,
        data_rows=[("row_alpha", ["Alpha", "1"])],
        section=first_section,
    )
    first.table_id = "table_1"
    first.confidence = 0.92
    first.fragments[0].fragment_id = "fragment_1"

    second_sheet, second = _presentation_table(
        "清单2",
        1,
        page=2,
        data_rows=[("row_beta", ["Beta", "2"])],
    )
    second.table_id = "table_2"
    second.confidence = 0.88
    second.fragments[0].fragment_id = "fragment_2"
    second.rows.extend(
        [
            LogicalRow(
                row_id="section_b_row",
                source_ref=SourceRef(sheet_name="清单2", range="A5:B5"),
                role="section_header",
                values=["", "Section B"],
                section_path=["Section B"],
            ),
            LogicalRow(
                row_id="row_gamma",
                source_ref=SourceRef(sheet_name="清单2", range="A6:B6"),
                role="data",
                values=["Gamma", "3"],
                section_path=["Section B"],
            ),
        ]
    )
    second_section = TableSection(
        section_id="section_b",
        title="Section B",
        source_ref=SourceRef(sheet_name="清单2", range="A5:B5"),
        row_ids=["row_gamma"],
    )
    second.sections = [second_section]
    snapshot, ir = _workbook_ir([(first_sheet, [first]), (second_sheet, [second])])
    member_row_roles = [row.role for row in second.rows]
    member_paths = [list(row.section_path) for row in second.rows]

    groups, _ = link_table_continuations(snapshot, ir)

    assert len(groups) == 1
    group = groups[0]
    aggregate = group.logical_table
    assert group.continuation_id == stable_id("continuation", "book.xlsx", "table_1", "table_2")
    assert aggregate.table_id == stable_id("table", group.continuation_id, "aggregate")
    assert group.confidence == 0.88
    assert [ref.key for ref in group.source_refs] == ["清单1!A1:B5", "清单2!A1:B5"]
    assert [fragment.fragment_id for fragment in aggregate.fragments] == [
        "fragment_1",
        "fragment_2",
    ]
    assert [ref.key for ref in aggregate.columns[0].source_refs] == ["清单1!A3", "清单2!A3"]
    assert [row.role for row in aggregate.rows[:3]] == ["title", "context", "header"]
    assert [row.role for row in aggregate.rows[4:7]] == [
        "repeated_title",
        "repeated_context",
        "repeated_header",
    ]
    assert next(row for row in aggregate.rows if row.row_id == "row_beta").section_path == [
        "Section A"
    ]
    assert next(row for row in aggregate.rows if row.row_id == "row_gamma").section_path == [
        "Section B"
    ]
    assert next(
        section for section in aggregate.sections if section.section_id == "section_a"
    ).row_ids == [
        "row_alpha",
        "row_beta",
    ]
    assert [row.role for row in second.rows] == member_row_roles
    assert [row.section_path for row in second.rows] == member_paths
