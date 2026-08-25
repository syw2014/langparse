from openpyxl import Workbook

from langparse.parsers.excel_parser import ExcelParser
from langparse.workbooks.assembly import assemble_workbook
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


def _snapshot(values: dict[str, object]) -> WorkbookSnapshot:
    return WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
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
        ],
    )


def test_assembly_promotes_two_blank_band_regions_to_two_logical_tables():
    snapshot = _snapshot(
        {
            "A1": "Name",
            "B1": "Value",
            "A2": "Alpha",
            "B2": 1,
            "A5": "Name",
            "B5": "Value",
            "A6": "Beta",
            "B6": 2,
        }
    )

    ir, diagnostics = assemble_workbook(snapshot)

    assert [block.kind for block in ir.sheets[0].blocks] == ["logical_table", "logical_table"]
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert diagnostics.block_count_by_kind == {"logical_table": 2}


def test_assembly_keeps_one_cell_candidate_unclassified():
    ir, diagnostics = assemble_workbook(_snapshot({"C3": "note"}))

    assert [block.kind for block in ir.sheets[0].blocks] == ["unclassified"]
    assert diagnostics.coverage_ratio == 1.0


def test_excel_parser_uses_semantic_workbook_assembly(tmp_path):
    path = tmp_path / "table.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Value"])
    sheet.append(["Alpha", 1])
    workbook.save(path)

    parsed = ExcelParser().parse_result(path)

    assert parsed.structure is not None
    block = parsed.structure.sheets[0].blocks[0]
    assert block.kind == "logical_table"
    assert block.logical_table is not None
    assert [row.role for row in block.logical_table.rows] == ["header", "data"]
