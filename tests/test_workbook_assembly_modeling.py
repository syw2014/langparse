from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from langparse.workbooks.assembly import assemble_workbook
from langparse.workbooks.modeling import (
    ModelIdentity,
    ProviderReply,
    RequiredWorkbookDisambiguationError,
    WorkbookDisambiguation,
)
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


class SelectingAdapter:
    def __init__(self, *, kind: str, confidence: float = 0.99) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")
        self.kind = kind
        self.confidence = confidence
        self.requests = []

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        self.requests.append((request, timeout_seconds))
        envelope = json.loads(request.body)
        case = envelope["cases"][0]
        selected = next(choice for choice in case["choices"] if choice["kind"] == self.kind)
        return ProviderReply(
            body=json.dumps(
                {
                    "schema_version": envelope["schema_version"],
                    "request_checksum": request.request_checksum,
                    "decisions": [
                        {
                            "case_id": case["case_id"],
                            "status": "selected",
                            "choice_id": selected["choice_id"],
                            "confidence": self.confidence,
                            "reason_codes": ["scripted_selection"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


class FailingAdapter:
    def __init__(self) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")
        self.calls = 0

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        self.calls += 1
        raise RuntimeError("private provider body")


class AbstainingAdapter:
    def __init__(self) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        envelope = json.loads(request.body)
        case = envelope["cases"][0]
        return ProviderReply(
            body=json.dumps(
                {
                    "schema_version": envelope["schema_version"],
                    "request_checksum": request.request_checksum,
                    "decisions": [
                        {
                            "case_id": case["case_id"],
                            "status": "abstained",
                            "confidence": 0.0,
                            "reason_codes": ["scripted_abstention"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


class ExplodingAdapter:
    @property
    def identity(self):
        raise AssertionError("adapter identity must not be reached")

    def complete(self, request, *, timeout_seconds: float):
        raise AssertionError("adapter complete must not be reached")


class MalformedAdapter:
    def __init__(self, shape: str) -> None:
        self.identity = (
            object()
            if shape == "identity"
            else ModelIdentity(provider="scripted", model="fixture", revision="1")
        )
        self.shape = shape

    def complete(self, request, *, timeout_seconds: float):
        assert self.shape == "reply"
        return SimpleNamespace(body="private malformed reply")


def sparse_text_snapshot(*, two_regions: bool = False) -> WorkbookSnapshot:
    cells = {
        "A1": _cell("A1", "左上"),
        "B2": _cell("B2", "右下"),
    }
    used_range = "A1:B2"
    if two_regions:
        cells.update(
            {
                "A5": _cell("A5", "第二左上"),
                "B6": _cell("B6", "第二右下"),
            }
        )
        used_range = "A1:B6"
    return WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                used_range=used_range,
                cells=cells,
            )
        ],
    )


def _cell(coordinate: str, value: str) -> CellSnapshot:
    return CellSnapshot(
        coordinate=coordinate,
        raw_value=value,
        display_value=value,
        data_type="s",
    )


def nonexportable_sparse_snapshot(hidden_fact: str) -> WorkbookSnapshot:
    snapshot = sparse_text_snapshot()
    sheet = snapshot.sheets[0]
    if hidden_fact == "row":
        sheet.hidden_rows.append(2)
    elif hidden_fact == "column":
        sheet.hidden_columns.append("B")
    else:
        sheet.cells["B2"].hidden = True
    return snapshot


def test_auto_materializes_a_selected_choice_from_snapshot_facts():
    snapshot = sparse_text_snapshot()
    adapter = SelectingAdapter(kind="text")
    before = deepcopy(snapshot)

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(adapter),
    )

    block = ir.sheets[0].blocks[0]
    assert block.kind == "text"
    assert block.text is not None
    assert [line.text for line in block.text.lines] == ["左上", "右下"]
    assert snapshot == before
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert diagnostics.source_ref_validity_ratio == 1.0
    assert diagnostics.model_calls[0]["outcome"] == "accepted"


def test_auto_provider_failure_preserves_the_current_unclassified_fallback():
    snapshot = sparse_text_snapshot()
    adapter = FailingAdapter()

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(adapter),
    )

    assert ir.sheets[0].blocks[0].kind == "unclassified"
    assert diagnostics.status == "success"
    assert diagnostics.ambiguous_regions[0]["candidate_kind"] == "unclassified"
    assert diagnostics.model_calls[0]["outcome"] == "provider_error"
    assert "private provider body" not in repr(diagnostics)
    assert adapter.calls == 2


@pytest.mark.parametrize("shape", ["identity", "reply"])
@pytest.mark.parametrize("mode", ["auto", "required"])
def test_assembly_contains_malformed_adapter_boundaries(shape: str, mode: str):
    configured = getattr(WorkbookDisambiguation, mode)(MalformedAdapter(shape))

    if mode == "auto":
        ir, diagnostics = assemble_workbook(
            sparse_text_snapshot(),
            disambiguation=configured,
        )
        assert ir.sheets[0].blocks[0].kind == "unclassified"
    else:
        with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
            assemble_workbook(
                sparse_text_snapshot(),
                disambiguation=configured,
            )
        diagnostics = caught.value.diagnostics

    assert diagnostics.model_calls
    assert "private malformed reply" not in repr(diagnostics.model_calls)


def test_model_reported_confidence_does_not_replace_local_choice_score():
    snapshot = sparse_text_snapshot()
    adapter = SelectingAdapter(kind="text", confidence=0.99)

    ir, _ = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(adapter),
    )

    assert ir.sheets[0].blocks[0].confidence == 0.4


def test_required_materialization_failure_raises_with_sanitized_diagnostics(monkeypatch):
    snapshot = sparse_text_snapshot()
    adapter = SelectingAdapter(kind="text")
    monkeypatch.setattr(
        "langparse.workbooks.assembly.interpret_text_block",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret body")),
    )

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(adapter),
        )

    assert "secret body" not in repr(caught.value.diagnostics)
    assert caught.value.diagnostics.model_calls[0]["outcome"] == "materialization_error"
    assert caught.value.diagnostics.model_calls[0]["error_type"] == "RuntimeError"


def test_auto_materialization_failure_returns_the_deterministic_unclassified_block(monkeypatch):
    snapshot = sparse_text_snapshot()
    adapter = SelectingAdapter(kind="text")
    monkeypatch.setattr(
        "langparse.workbooks.assembly.interpret_text_block",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret body")),
    )

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(adapter),
    )

    block = ir.sheets[0].blocks[0]
    assert block.kind == "unclassified"
    assert block.diagnostics == [{"reason_code": "insufficient_semantic_evidence"}]
    assert diagnostics.model_calls[0]["outcome"] == "materialization_error"
    assert "secret body" not in repr(diagnostics)


@pytest.mark.parametrize("mode", ["auto", "required"])
def test_second_materialization_failure_atomically_reverts_every_attempted_selection(
    monkeypatch,
    mode: str,
):
    from langparse.workbooks import assembly as assembly_module

    snapshot = sparse_text_snapshot(two_regions=True)
    original = assembly_module.interpret_text_block
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private second materialization")
        return original(*args, **kwargs)

    monkeypatch.setattr(assembly_module, "interpret_text_block", fail_second)
    configured = getattr(WorkbookDisambiguation, mode)(SelectingAdapter(kind="text"))

    if mode == "auto":
        ir, diagnostics = assemble_workbook(snapshot, disambiguation=configured)
    else:
        with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
            assemble_workbook(snapshot, disambiguation=configured)
        diagnostics = caught.value.diagnostics
        ir = None
        assert caught.value.case_ids == tuple(audit["case_id"] for audit in diagnostics.model_calls)

    if ir is not None:
        assert [block.kind for block in ir.sheets[0].blocks] == [
            "unclassified",
            "unclassified",
        ]
    assert [audit["outcome"] for audit in diagnostics.model_calls] == [
        "materialization_error",
        "materialization_error",
    ]
    assert [audit["validation_codes"] for audit in diagnostics.model_calls] == [
        ("materialization_error",),
        ("materialization_error",),
    ]
    assert "private second materialization" not in repr(diagnostics)


def test_default_and_off_are_deep_equal_and_do_not_construct_model_runtime(monkeypatch):
    snapshot = sparse_text_snapshot()
    expected_ir, expected_diagnostics = assemble_workbook(snapshot)

    monkeypatch.setattr(
        "langparse.workbooks.modeling.disambiguation.MemoryDecisionCache",
        lambda: (_ for _ in ()).throw(AssertionError("model runtime must not be constructed")),
    )

    default_ir, default_diagnostics = assemble_workbook(snapshot)
    off_ir, off_diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.off(),
    )

    assert default_ir == expected_ir
    assert default_diagnostics == expected_diagnostics
    assert off_ir == expected_ir
    assert off_diagnostics == expected_diagnostics
    assert default_diagnostics.model_calls == []
    assert off_diagnostics.model_calls == []


def test_off_uses_the_pre_model_deterministic_assembly_path(monkeypatch):
    snapshot = sparse_text_snapshot()
    monkeypatch.setattr(
        "langparse.workbooks.assembly.assess_candidate_region",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("off must not enter model assessment")
        ),
    )

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.off(),
    )

    assert ir.sheets[0].blocks[0].kind == "unclassified"
    assert diagnostics.model_calls == []
    assert diagnostics.status == "success"


def test_auto_clear_regions_make_zero_adapter_calls():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                used_range="A1:B2",
                cells={
                    "A1": _cell("A1", "Name"),
                    "B1": _cell("B1", "Value"),
                    "A2": _cell("A2", "Alpha"),
                    "B2": _cell("B2", "1"),
                },
            )
        ],
    )

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(ExplodingAdapter()),
    )

    assert ir.sheets[0].blocks[0].kind == "logical_table"
    assert diagnostics.model_calls == []


def test_required_hidden_sheet_uses_a_content_free_local_case_id_without_adapter_work():
    first = sparse_text_snapshot()
    first.sheets[0].visibility = "hidden"
    first.sheets[0].cells["A1"].display_value = "hidden body one"
    second = deepcopy(first)
    second.sheets[0].cells["A1"].display_value = "hidden body two"

    def required_error(snapshot):
        with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
            assemble_workbook(
                snapshot,
                disambiguation=WorkbookDisambiguation.required(ExplodingAdapter()),
            )
        return caught.value

    first_error = required_error(first)
    second_error = required_error(second)

    assert first_error.case_ids == second_error.case_ids
    assert first_error.diagnostics.ambiguous_regions[0]["candidate_kind"] == "unclassified"
    assert first_error.diagnostics.model_calls[0]["case_id"] == first_error.case_ids[0]
    assert first_error.diagnostics.model_calls[0]["outcome"] == "hidden_content"
    assert "hidden body" not in repr(first_error.diagnostics)


@pytest.mark.parametrize("hidden_fact", ["row", "column", "cell"])
def test_auto_nonexportable_candidate_keeps_local_fallback_without_adapter_work(hidden_fact):
    snapshot = nonexportable_sparse_snapshot(hidden_fact)

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(ExplodingAdapter()),
    )

    assert ir.sheets[0].blocks[0].kind == "unclassified"
    assert diagnostics.model_calls[0]["outcome"] == "hidden_content"
    assert "右下" not in repr(diagnostics.model_calls)


def test_required_cached_formula_candidate_is_local_unavailable_and_content_free():
    snapshot = sparse_text_snapshot()
    formula_cell = snapshot.sheets[0].cells["B2"]
    formula_cell.raw_value = "=SECRET()"
    formula_cell.display_value = "CACHED_SECRET"
    formula_cell.formula = "=SECRET()"
    formula_cell.cached_value = "CACHED_SECRET"

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(ExplodingAdapter()),
        )

    assert caught.value.case_ids == (caught.value.diagnostics.model_calls[0]["case_id"],)
    assert caught.value.diagnostics.model_calls[0]["outcome"] == "formula_content"
    serialized = repr(caught.value)
    assert "SECRET" not in serialized
    assert "CACHED_SECRET" not in serialized


@pytest.mark.parametrize("hidden_fact", ["row", "column", "cell"])
def test_required_nonexportable_candidate_raises_without_adapter_work(hidden_fact):
    snapshot = nonexportable_sparse_snapshot(hidden_fact)

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(ExplodingAdapter()),
        )

    assert caught.value.diagnostics.ambiguous_regions[0]["candidate_kind"] == "unclassified"
    assert caught.value.diagnostics.model_calls[0]["case_id"] == caught.value.case_ids[0]
    assert caught.value.diagnostics.model_calls[0]["outcome"] == "hidden_content"


def test_required_aggregates_unavailable_and_disambiguator_unresolved_case_ids():
    snapshot = sparse_text_snapshot()
    snapshot.sheets.append(
        SheetSnapshot(
            name="Hidden",
            index=1,
            visibility="hidden",
            used_range="A1:B2",
            cells={
                "A1": _cell("A1", "hidden left"),
                "B2": _cell("B2", "hidden right"),
            },
        )
    )

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(AbstainingAdapter()),
        )

    diagnostics = caught.value.diagnostics
    assert caught.value.case_ids == tuple(audit["case_id"] for audit in diagnostics.model_calls)
    assert [audit["outcome"] for audit in diagnostics.model_calls] == [
        "abstained",
        "hidden_content",
    ]
    assert [item["sheet_name"] for item in diagnostics.ambiguous_regions] == [
        "Data",
        "Hidden",
    ]


@pytest.mark.parametrize(
    ("adapter", "outcome"),
    [(AbstainingAdapter(), "abstained"), (FailingAdapter(), "adapter_error")],
)
def test_early_required_disambiguator_error_retains_deterministic_diagnostics(
    adapter,
    outcome,
):
    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            sparse_text_snapshot(),
            disambiguation=WorkbookDisambiguation.required(adapter),
        )

    diagnostics = caught.value.diagnostics
    assert diagnostics.status == "failed"
    assert diagnostics.ambiguous_regions[0]["candidate_kind"] == "unclassified"
    assert diagnostics.model_calls[0]["outcome"] == outcome
    assert caught.value.case_ids == (diagnostics.model_calls[0]["case_id"],)
    assert "private provider body" not in repr(diagnostics)


def test_auto_continuation_failure_rolls_back_all_model_selected_blocks(monkeypatch):
    snapshot = sparse_text_snapshot(two_regions=True)
    monkeypatch.setattr(
        "langparse.workbooks.assembly.link_table_continuations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private continuation")),
    )

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(SelectingAdapter(kind="text")),
    )

    assert [block.kind for block in ir.sheets[0].blocks] == [
        "unclassified",
        "unclassified",
    ]
    assert diagnostics.warnings == ["cross_sheet_continuation_fallback:RuntimeError"]
    assert [audit["outcome"] for audit in diagnostics.model_calls] == [
        "validation_error",
        "validation_error",
    ]
    assert [audit["validation_codes"] for audit in diagnostics.model_calls] == [
        ("continuation_error",),
        ("continuation_error",),
    ]
    assert "private continuation" not in repr(diagnostics)


def test_required_continuation_failure_raises_for_all_reverted_case_ids(monkeypatch):
    snapshot = sparse_text_snapshot(two_regions=True)
    monkeypatch.setattr(
        "langparse.workbooks.assembly.link_table_continuations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private continuation")),
    )

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(SelectingAdapter(kind="text")),
        )

    diagnostics = caught.value.diagnostics
    assert caught.value.case_ids == tuple(audit["case_id"] for audit in diagnostics.model_calls)
    assert [audit["outcome"] for audit in diagnostics.model_calls] == [
        "validation_error",
        "validation_error",
    ]
    assert diagnostics.warnings == ["cross_sheet_continuation_fallback:RuntimeError"]


def test_auto_validation_failure_reverts_all_selected_blocks_transactionally(monkeypatch):
    snapshot = sparse_text_snapshot(two_regions=True)
    adapter = SelectingAdapter(kind="text")
    validations = iter(((0.5, ["Data!Z99"]), (1.0, [])))
    monkeypatch.setattr(
        "langparse.workbooks.assembly.validate_workbook_source_refs",
        lambda *_args, **_kwargs: next(validations),
    )

    ir, diagnostics = assemble_workbook(
        snapshot,
        disambiguation=WorkbookDisambiguation.auto(adapter),
    )

    assert [block.kind for block in ir.sheets[0].blocks] == [
        "unclassified",
        "unclassified",
    ]
    assert diagnostics.status == "success"
    assert diagnostics.source_ref_validity_ratio == 1.0
    assert [audit["outcome"] for audit in diagnostics.model_calls] == [
        "validation_error",
        "validation_error",
    ]
    assert [audit["validation_codes"] for audit in diagnostics.model_calls] == [
        ("invalid_source_refs",),
        ("invalid_source_refs",),
    ]
    assert [request[0].case_ids[0] for request in adapter.requests] == [
        audit["case_id"] for audit in diagnostics.model_calls
    ]


def test_required_validation_failure_raises_all_reverted_case_ids(monkeypatch):
    snapshot = sparse_text_snapshot(two_regions=True)
    adapter = SelectingAdapter(kind="text")
    validations = iter(((0.5, ["Data!Z99"]), (1.0, [])))
    monkeypatch.setattr(
        "langparse.workbooks.assembly.validate_workbook_source_refs",
        lambda *_args, **_kwargs: next(validations),
    )

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        assemble_workbook(
            snapshot,
            disambiguation=WorkbookDisambiguation.required(adapter),
        )

    assert caught.value.case_ids == tuple(
        audit["case_id"] for audit in caught.value.diagnostics.model_calls
    )
    assert [audit["outcome"] for audit in caught.value.diagnostics.model_calls] == [
        "validation_error",
        "validation_error",
    ]
    assert "Data!Z99" not in repr(caught.value.diagnostics)
