from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


def test_baseline_assembly_covers_every_non_empty_cell():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                used_range="A1:B2",
                cells={
                    "A1": CellSnapshot(
                        coordinate="A1",
                        raw_value="Header",
                        display_value="Header",
                    ),
                    "B2": CellSnapshot(coordinate="B2", raw_value=2, display_value="2"),
                },
            )
        ],
    )

    ir, diagnostics = assemble_baseline(snapshot)

    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert diagnostics.block_count_by_kind == {"unclassified": 1}
    assert ir.sheets[0].blocks[0].source_refs[0].range == "A1:B2"
    assert ir.sheets[0].blocks[0].cell_refs == ["A1", "B2"]


def test_empty_sheet_produces_no_block_but_is_preserved():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[SheetSnapshot(name="Empty", index=0)],
    )

    ir, diagnostics = assemble_baseline(snapshot)

    assert ir.sheets[0].blocks == []
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True


def test_baseline_assigns_formula_comment_link_and_merged_subordinate_cells():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Facts",
                index=0,
                used_range="A1:D1",
                cells={
                    "A1": CellSnapshot(coordinate="A1", formula="=1+1"),
                    "B1": CellSnapshot(coordinate="B1", comment="note"),
                    "C1": CellSnapshot(coordinate="C1", hyperlink="https://example.com"),
                    "D1": CellSnapshot(coordinate="D1", merge_anchor="C1"),
                },
            )
        ],
    )

    ir, diagnostics = assemble_baseline(snapshot)

    assert ir.sheets[0].blocks[0].cell_refs == ["A1", "B1", "C1", "D1"]
    assert diagnostics.coverage_ratio == 1.0
