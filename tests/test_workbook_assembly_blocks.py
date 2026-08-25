from langparse.workbooks.assembly import assemble_workbook, validate_workbook_source_refs
from langparse.workbooks.types import (
    CellSnapshot,
    FormBlock,
    FormField,
    SheetSnapshot,
    SourceRef,
    WorkbookSnapshot,
)


def _snapshot(values: dict[str, object], used_range: str) -> WorkbookSnapshot:
    sheet = SheetSnapshot(
        name="Data",
        index=0,
        used_range=used_range,
        cells={
            coordinate: CellSnapshot(
                coordinate=coordinate,
                raw_value=value,
                display_value=str(value),
            )
            for coordinate, value in values.items()
        },
    )
    return WorkbookSnapshot(source="book.xlsx", filename="book.xlsx", sheets=[sheet])


def _continuation_snapshot() -> WorkbookSnapshot:
    sheets = []
    for index, page_number in enumerate((1, 2), start=1):
        values = {
            "A1": "工程清单",
            "A2": f"第 {page_number} 页 共 2 页",
            "A3": "Name",
            "B3": "Value",
            "A4": page_number,
            "B4": f"Item {page_number}",
        }
        sheets.append(
            SheetSnapshot(
                name=f"清单{index}",
                index=index - 1,
                used_range="A1:B4",
                cells={
                    coordinate: CellSnapshot(
                        coordinate=coordinate,
                        raw_value=value,
                        display_value=str(value),
                    )
                    for coordinate, value in values.items()
                },
            )
        )
    return WorkbookSnapshot(source="book.xlsx", filename="book.xlsx", sheets=sheets)


def test_assembly_classifies_mixed_form_and_table_regions():
    snapshot = _snapshot(
        {
            "A1": "项目登记",
            "A2": "项目名称",
            "B2": "道路工程",
            "A3": "建设单位",
            "B3": "示例公司",
            "A6": "Name",
            "B6": "Value",
            "A7": "Alpha",
            "B7": 1,
            "A8": "Beta",
            "B8": 2,
        },
        "A1:B8",
    )

    ir, diagnostics = assemble_workbook(snapshot)

    assert [block.kind for block in ir.sheets[0].blocks] == ["form", "logical_table"]
    assert ir.sheets[0].blocks[0].form is not None
    assert ir.sheets[0].blocks[1].logical_table is not None
    assert set(ir.sheets[0].blocks[0].cell_refs).isdisjoint(ir.sheets[0].blocks[1].cell_refs)
    assert diagnostics.block_count_by_kind == {"form": 1, "logical_table": 1}
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert diagnostics.source_ref_validity_ratio == 1.0


def test_assembly_keeps_ambiguous_sparse_region_explicit():
    snapshot = _snapshot({"A1": "左上", "B2": "右下"}, "A1:B2")

    ir, diagnostics = assemble_workbook(snapshot)

    block = ir.sheets[0].blocks[0]
    assert block.kind == "unclassified"
    assert block.confidence < 0.8
    assert block.diagnostics[0]["reason_code"] == "insufficient_semantic_evidence"
    assert diagnostics.ambiguous_regions == [
        {
            "sheet_name": "Data",
            "range": "A1:B2",
            "candidate_kind": "unclassified",
            "confidence": 0.5,
            "reason_codes": ["insufficient_semantic_evidence"],
        }
    ]


def test_assembly_links_cross_sheet_table_continuations():
    ir, diagnostics = assemble_workbook(_continuation_snapshot())

    assert len(ir.table_continuations) == 1
    assert diagnostics.continuation_candidates[0]["status"] == "accepted"
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert diagnostics.source_ref_validity_ratio == 1.0


def test_assembly_preserves_sheet_blocks_when_continuation_linking_fails(monkeypatch):
    def raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError

    monkeypatch.setattr(
        "langparse.workbooks.assembly.link_table_continuations",
        raise_runtime_error,
    )

    ir, diagnostics = assemble_workbook(_continuation_snapshot())

    assert [[block.kind for block in sheet.blocks] for sheet in ir.sheets] == [
        ["logical_table"],
        ["logical_table"],
    ]
    assert ir.table_continuations == []
    assert diagnostics.status == "success"
    assert diagnostics.warnings == ["cross_sheet_continuation_fallback:RuntimeError"]


def test_source_ref_validation_checks_aggregate_continuation_refs():
    snapshot = _continuation_snapshot()
    ir, _ = assemble_workbook(snapshot)
    continuation = ir.table_continuations[0]
    continuation.logical_table.columns[0].source_refs.append(
        SourceRef(sheet_name="清单2", range="Z99")
    )
    continuation.source_refs.append(SourceRef(sheet_name="清单2", range="Y99"))

    ratio, invalid_refs = validate_workbook_source_refs(snapshot, ir)

    assert ratio < 1.0
    assert invalid_refs == ["清单2!Y99", "清单2!Z99"]


def test_source_ref_validation_rejects_derived_refs_outside_sheet():
    snapshot = _snapshot({"A1": "note"}, "A1:A1")
    ir, _ = assemble_workbook(snapshot)
    block = ir.sheets[0].blocks[0]
    block.kind = "form"
    block.form = FormBlock(
        form_id="form_invalid",
        fields=[
            FormField(
                field_id="field_invalid",
                label="项目",
                value="道路",
                label_source_refs=[SourceRef(sheet_name="Data", range="A1")],
                value_source_refs=[SourceRef(sheet_name="Data", range="Z99")],
            )
        ],
    )

    ratio, invalid_refs = validate_workbook_source_refs(snapshot, ir)

    assert ratio < 1.0
    assert invalid_refs == ["Data!Z99"]
