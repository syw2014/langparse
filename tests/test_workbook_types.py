from langparse.types import ParseDiagnostics, ParsedStructure
from langparse.workbooks.types import (
    CellSnapshot,
    FormBlock,
    FormField,
    HeaderColumn,
    LogicalRow,
    LogicalTable,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    TableFragment,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)


def test_source_ref_and_ids_are_stable():
    ref = SourceRef(sheet_name="Data", range="A1:B2")
    assert ref.key == "Data!A1:B2"
    assert stable_id("table", ref.key) == stable_id("table", ref.key)
    assert stable_id("table", ref.key) != stable_id("table", "Data!A1:B3")


def test_workbook_snapshot_preserves_coordinate_facts():
    cell = CellSnapshot(coordinate="B2", raw_value="=A2*2", formula="=A2*2")
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:B2", cells={"B2": cell})
    snapshot = WorkbookSnapshot(source="book.xlsx", filename="book.xlsx", sheets=[sheet])
    assert snapshot.sheets[0].cells["B2"].formula == "=A2*2"


def test_workbook_ir_is_a_parsed_structure():
    block = WorkbookBlock(
        block_id="block-1",
        kind="unclassified",
        source_refs=[SourceRef(sheet_name="Data", range="A1:B2")],
    )
    ir = WorkbookIR(
        kind="workbook",
        workbook_id="wb-1",
        source="book.xlsx",
        sheets=[SheetIR(sheet_id="sheet-1", name="Data", index=0, blocks=[block])],
    )
    assert isinstance(ir, ParsedStructure)
    assert ir.kind == "workbook"
    assert ir.sheets[0].blocks[0].source_refs[0].key == "Data!A1:B2"


def test_logical_table_types_preserve_semantics_and_sources():
    header = HeaderColumn(column_id="col_a", coordinate="A", path=["其中", "人工费"])
    row = LogicalRow(
        row_id="row_1",
        source_ref=SourceRef(sheet_name="Data", range="A5:L5"),
        role="data",
    )
    fragment = TableFragment(
        fragment_id="frag_1",
        source_ref=SourceRef(sheet_name="Data", range="A1:L10"),
    )
    table = LogicalTable(
        table_id="table_1",
        title="清单",
        columns=[header],
        rows=[row],
        fragments=[fragment],
    )
    block = WorkbookBlock(
        block_id="b",
        kind="logical_table",
        logical_table=table,
    )

    assert block.logical_table is not None
    assert block.logical_table.columns[0].path == ["其中", "人工费"]
    assert block.logical_table.fragments[0].source_ref.key == "Data!A1:L10"


def test_semantic_block_types_preserve_payload_and_sources():
    field = FormField(
        field_id="field_1",
        label="项目名称",
        value="道路工程",
        label_source_refs=[SourceRef(sheet_name="Cover", range="A2")],
        value_source_refs=[SourceRef(sheet_name="Cover", range="B2")],
    )
    form = FormBlock(form_id="form_1", title="封面", fields=[field])
    block = WorkbookBlock(block_id="b", kind="form", form=form)

    assert block.form is not None
    assert block.form.fields[0].value_source_refs[0].key == "Cover!B2"
    assert block.logical_table is None


def test_parse_diagnostics_defaults_source_ref_validity_to_one():
    assert ParseDiagnostics().source_ref_validity_ratio == 1.0
