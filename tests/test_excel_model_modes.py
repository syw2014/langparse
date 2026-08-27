from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from langparse.parsers.excel_parser import ExcelParser
from langparse.services.parse_service import ParseService
from langparse.workbooks.modeling import (
    ModelIdentity,
    ProviderReply,
    RequiredWorkbookDisambiguationError,
    WorkbookDisambiguation,
)


class SelectingAdapter:
    def __init__(self, *, kind: str) -> None:
        self.identity = ModelIdentity(provider="scripted", model="fixture", revision="1")
        self.kind = kind
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
                            "confidence": 0.99,
                            "reason_codes": ["scripted_selection"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


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
                            "choice_id": None,
                            "confidence": 0.0,
                            "reason_codes": ["scripted_abstention"],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            provider_request_id="scripted-request",
        )


class RecordingAdapter:
    def __init__(self) -> None:
        self.identity = ModelIdentity(provider="recording", model="fixture", revision="1")
        self.requests = []

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
        self.requests.append((request, timeout_seconds))
        raise AssertionError("formula candidate must not reach Adapter.complete")


class MalformedAdapter:
    def __init__(self, shape: str) -> None:
        self.identity = (
            object()
            if shape == "identity"
            else ModelIdentity(provider="recording", model="fixture", revision="1")
        )
        self.shape = shape

    def complete(self, request, *, timeout_seconds: float):
        assert self.shape == "reply"
        return SimpleNamespace(body="private malformed reply")


def sparse_workbook(tmp_path):
    path = tmp_path / "sparse.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "左上"
    sheet["B2"] = "右下"
    workbook.save(path)
    return path


def _force_tentative_and_rollback_validator_failures(monkeypatch):
    source_ref_results = iter(((0.5, ["Data!Z99"]), (1.0, [])))
    row_conservation_results = iter((True, False))
    monkeypatch.setattr(
        "langparse.workbooks.assembly.validate_workbook_source_refs",
        lambda *_args, **_kwargs: next(source_ref_results),
    )
    monkeypatch.setattr(
        "langparse.workbooks.assembly._row_conservation_passed",
        lambda *_args, **_kwargs: next(row_conservation_results),
    )


def uncached_formula_workbook(tmp_path):
    path = tmp_path / "uncached-formula.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "左上"
    sheet["B2"] = "=SECRET()"
    workbook.save(path)
    return path


def scrub_runtime_fields(model_calls):
    return [
        {key: value for key, value in call.items() if key != "elapsed_ms"} for call in model_calls
    ]


def test_model_diagnostics_are_deterministic_and_json_serializable(tmp_path):
    path = sparse_workbook(tmp_path)
    first_adapter = SelectingAdapter(kind="text")
    second_adapter = SelectingAdapter(kind="text")

    first = ExcelParser(disambiguation=WorkbookDisambiguation.auto(first_adapter)).parse_result(
        path
    )
    second = ExcelParser(disambiguation=WorkbookDisambiguation.auto(second_adapter)).parse_result(
        path
    )

    first_json = ParseService().render_output(first, "json")
    second_json = ParseService().render_output(second, "json")
    assert json.loads(first_json)
    assert json.loads(second_json)
    assert first.structure == second.structure
    assert scrub_runtime_fields(first.diagnostics.model_calls) == scrub_runtime_fields(
        second.diagnostics.model_calls
    )


@pytest.mark.parametrize("mode", ["auto", "required"])
def test_enabled_configuration_reuses_cache_across_repeated_excel_parser_parses(
    tmp_path,
    mode: str,
):
    path = sparse_workbook(tmp_path)
    adapter = SelectingAdapter(kind="text")
    configured = getattr(WorkbookDisambiguation, mode)(adapter)
    parser = ExcelParser(disambiguation=configured)

    first = parser.parse_result(path)
    second = parser.parse_result(path)

    assert len(adapter.requests) == 1
    assert first.diagnostics.model_calls[0]["cache_status"] == "miss"
    assert second.diagnostics.model_calls[0]["cache_status"] == "hit"
    assert second.diagnostics.model_calls[0]["attempts"] == 0
    assert first.structure == second.structure


def test_excel_parser_does_not_swallow_required_disambiguation_failure(tmp_path):
    path = sparse_workbook(tmp_path)
    parser = ExcelParser(disambiguation=WorkbookDisambiguation.required(AbstainingAdapter()))

    with pytest.raises(RequiredWorkbookDisambiguationError):
        parser.parse_result(path)


def test_excel_parser_propagates_required_rollback_validator_failure(tmp_path, monkeypatch):
    path = sparse_workbook(tmp_path)
    _force_tentative_and_rollback_validator_failures(monkeypatch)

    with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
        ExcelParser(
            disambiguation=WorkbookDisambiguation.required(SelectingAdapter(kind="text"))
        ).parse_result(path)

    assert caught.value.case_ids == tuple(
        audit["case_id"] for audit in caught.value.diagnostics.model_calls
    )
    assert caught.value.diagnostics.status == "failed"
    assert caught.value.diagnostics.ambiguous_regions[0]["candidate_kind"] == "unclassified"


@pytest.mark.parametrize("shape", ["identity", "reply"])
@pytest.mark.parametrize("mode", ["auto", "required"])
def test_excel_parser_contains_malformed_adapter_boundaries(tmp_path, shape: str, mode: str):
    path = sparse_workbook(tmp_path)
    configured = getattr(WorkbookDisambiguation, mode)(MalformedAdapter(shape))

    if mode == "auto":
        parsed = ExcelParser(disambiguation=configured).parse_result(path)
        assert parsed.structure.sheets[0].blocks[0].kind == "unclassified"
        assert parsed.diagnostics.model_calls
    else:
        with pytest.raises(RequiredWorkbookDisambiguationError) as caught:
            ExcelParser(disambiguation=configured).parse_result(path)
        parsed = caught.value

    assert "private malformed reply" not in repr(parsed)


def test_excel_parser_never_sends_real_ooxml_uncached_formula_candidate(tmp_path):
    path = uncached_formula_workbook(tmp_path)
    adapter = RecordingAdapter()

    parsed = ExcelParser(
        disambiguation=WorkbookDisambiguation.auto(adapter),
    ).parse_result(path)

    formula_cell = parsed.structure.snapshot.sheets[0].cells["B2"]
    assert formula_cell.formula == "=SECRET()"
    assert formula_cell.cached_value is None
    assert formula_cell.display_value == "=SECRET()"
    assert adapter.requests == []
    assert parsed.diagnostics.model_calls[0]["outcome"] == "formula_content"
    assert "SECRET" not in repr(parsed.diagnostics.model_calls)


def test_excel_parser_default_off_cannot_create_model_or_network_work(
    tmp_path,
    monkeypatch,
):
    path = sparse_workbook(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-read")
    monkeypatch.setattr(
        "langparse.workbooks.modeling.disambiguation.MemoryDecisionCache",
        lambda: (_ for _ in ()).throw(AssertionError("model runtime must not be constructed")),
    )

    def explode_socket(*_args, **_kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(socket, "create_connection", explode_socket)

    parsed = ExcelParser().parse_result(path)

    assert parsed.structure.sheets[0].blocks[0].kind == "unclassified"
    assert parsed.diagnostics.model_calls == []
    assert parsed.diagnostics.status == "success"
