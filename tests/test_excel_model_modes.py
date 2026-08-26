from __future__ import annotations

import json
import socket

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

    def complete(self, request, *, timeout_seconds: float) -> ProviderReply:
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


def sparse_workbook(tmp_path):
    path = tmp_path / "sparse.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "左上"
    sheet["B2"] = "右下"
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


def test_excel_parser_does_not_swallow_required_disambiguation_failure(tmp_path):
    path = sparse_workbook(tmp_path)
    parser = ExcelParser(disambiguation=WorkbookDisambiguation.required(AbstainingAdapter()))

    with pytest.raises(RequiredWorkbookDisambiguationError):
        parser.parse_result(path)


def test_excel_parser_default_off_cannot_create_model_or_network_work(
    tmp_path,
    monkeypatch,
):
    path = sparse_workbook(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-read")
    monkeypatch.setattr(
        "langparse.workbooks.assembly.WorkbookRegionDisambiguator",
        lambda: (_ for _ in ()).throw(AssertionError("model runtime must not be constructed")),
    )

    def explode_socket(*_args, **_kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(socket, "create_connection", explode_socket)

    parsed = ExcelParser().parse_result(path)

    assert parsed.structure.sheets[0].blocks[0].kind == "unclassified"
    assert parsed.diagnostics.model_calls == []
    assert parsed.diagnostics.status == "success"
