from __future__ import annotations

import json
from dataclasses import replace

import pytest

from langparse.workbooks.classification import assess_candidate_region
from langparse.workbooks.modeling import contract
from langparse.workbooks.modeling.cache import MemoryDecisionCache
from langparse.workbooks.modeling.contract import (
    build_model_request,
    build_region_case,
    decode_model_reply,
    response_checksum,
)
from langparse.workbooks.modeling.ports import (
    InvalidRegionAmbiguityCaseError,
    WorkbookModelResponseError,
)
from langparse.workbooks.modeling.types import (
    REGION_PRIVACY_VERSION,
    ModelIdentity,
    ProviderReply,
    RegionAmbiguityCase,
    RegionCellCue,
    RegionChoice,
)
from langparse.workbooks.types import CandidateRegion, CellSnapshot, SheetSnapshot, SourceRef


def test_region_request_contains_only_candidate_local_safe_cues():
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()

    case = build_region_case(sheet, candidate, assessment)
    request = build_model_request(
        case,
        ModelIdentity(provider="recording", model="fixture", revision="1"),
    )

    payload = json.loads(request.body)
    assert payload["schema_version"] == 1
    assert payload["prompt_version"] == "region-choice-v1"
    assert payload["privacy_version"] == REGION_PRIVACY_VERSION
    assert request.privacy_version == REGION_PRIVACY_VERSION
    assert payload["request_checksum"] == request.request_checksum
    assert payload["cases"][0]["source_range"] == "A1:B2"
    assert [cell["coordinate"] for cell in payload["cases"][0]["cells"]] == ["A1", "B2"]
    assert payload["cases"][0]["cells"] == [
        {
            "colspan": 1,
            "coordinate": "A1",
            "display_text": "Name",
            "merge_anchor": None,
            "rowspan": 1,
            "style_fingerprint": "header-style",
            "value_type": "s",
        },
        {
            "colspan": 1,
            "coordinate": "B2",
            "display_text": "7",
            "merge_anchor": None,
            "rowspan": 1,
            "style_fingerprint": "number-style",
            "value_type": "n",
        },
    ]
    assert request.choice_ids_by_case == (
        (case.case_id, tuple(choice.choice_id for choice in case.choices)),
    )

    serialized = request.body.decode("utf-8")
    assert "C9" not in serialized
    assert "=SECRET()" not in serialized
    assert "private comment" not in serialized
    assert "https://secret.example" not in serialized
    assert "local comment" not in serialized
    assert "https://local-secret.example" not in serialized


def test_request_checksum_changes_with_facts_choices_and_model_identity():
    base = request_fixture()

    assert request_checksum(base) != request_checksum(replace_cell_text(base, "changed"))
    assert request_checksum(base) != request_checksum(replace_choice_kind(base, "form"))
    assert request_checksum(base) != request_checksum(base, model="fixture-2")


def test_privacy_version_partitions_fact_request_and_cache_material(monkeypatch):
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    original_case = build_region_case(sheet, candidate, assessment)
    identity = ModelIdentity(provider="recording", model="fixture", revision="1")
    original_request = build_model_request(original_case, identity)
    cache = MemoryDecisionCache()
    cache.put(original_request.request_checksum, b"validated-response")

    monkeypatch.setattr(contract, "REGION_PRIVACY_VERSION", "region-privacy-v2")
    revised_case = build_region_case(sheet, candidate, assessment)
    revised_request = build_model_request(revised_case, identity)

    assert revised_case.fact_digest != original_case.fact_digest
    assert revised_request.privacy_version == "region-privacy-v2"
    assert json.loads(revised_request.body)["privacy_version"] == "region-privacy-v2"
    assert revised_request.request_checksum != original_request.request_checksum
    assert cache.get(revised_request.request_checksum) is None


def test_region_case_rejects_hidden_cell_without_disclosing_its_contents():
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    sheet.cells["A2"] = CellSnapshot(
        coordinate="A2",
        raw_value="hidden value",
        display_value="hidden secret one",
        hidden=True,
    )
    candidate.cell_refs.append("A2")
    assessment = assess_candidate_region(sheet, candidate)

    with pytest.raises(InvalidRegionAmbiguityCaseError) as first_error:
        build_region_case(sheet, candidate, assessment)
    sheet.cells["A2"].display_value = "hidden secret two"
    with pytest.raises(InvalidRegionAmbiguityCaseError) as second_error:
        build_region_case(sheet, candidate, assessment)

    assert str(first_error.value) == str(second_error.value)
    assert "hidden secret" not in str(first_error.value)


@pytest.mark.parametrize("hidden_fact", ["row", "column"])
def test_region_case_rejects_hidden_row_or_column(hidden_fact: str):
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    if hidden_fact == "row":
        sheet.hidden_rows.append(2)
    else:
        sheet.hidden_columns.append("B")
    assessment = assess_candidate_region(sheet, candidate)

    with pytest.raises(InvalidRegionAmbiguityCaseError, match="hidden candidate content"):
        build_region_case(sheet, candidate, assessment)


def test_region_case_rejects_hidden_merged_child_in_candidate_envelope():
    sheet, candidate, _ = ambiguous_region_with_sensitive_facts()
    sheet.cells["B1"] = CellSnapshot(
        coordinate="B1",
        merge_anchor="A1",
        hidden=True,
    )
    assessment = assess_candidate_region(sheet, candidate)

    with pytest.raises(InvalidRegionAmbiguityCaseError, match="hidden candidate content"):
        build_region_case(sheet, candidate, assessment)


@pytest.mark.parametrize(
    ("coordinate", "merge_anchor"),
    [
        pytest.param("A2", None, id="cell_absent_from_candidate_refs"),
        pytest.param("B1", "A1", id="merged_child"),
    ],
)
def test_region_case_rejects_formula_anywhere_in_candidate_envelope_without_disclosure(
    coordinate: str,
    merge_anchor: str | None,
):
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    sheet.cells[coordinate] = CellSnapshot(
        coordinate=coordinate,
        raw_value="=PRIVATE_FORMULA_ONE()",
        display_value="private cached result one",
        formula="=PRIVATE_FORMULA_ONE()",
        cached_value="private cached result one",
        merge_anchor=merge_anchor,
    )

    with pytest.raises(InvalidRegionAmbiguityCaseError) as first_error:
        build_region_case(sheet, candidate, assessment)

    sheet.cells[coordinate].raw_value = "=PRIVATE_FORMULA_TWO()"
    sheet.cells[coordinate].display_value = "private cached result two"
    sheet.cells[coordinate].formula = "=PRIVATE_FORMULA_TWO()"
    sheet.cells[coordinate].cached_value = "private cached result two"
    with pytest.raises(InvalidRegionAmbiguityCaseError) as second_error:
        build_region_case(sheet, candidate, assessment)

    assert str(first_error.value) == str(second_error.value)
    assert "PRIVATE_FORMULA" not in str(first_error.value)
    assert "private cached result" not in str(first_error.value)


def test_region_case_rejects_snapshot_mapping_coordinate_mismatch_before_projection():
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    sheet.cells["A1"] = CellSnapshot(
        coordinate="C9",
        raw_value="outside secret",
        display_value="outside secret",
    )

    with pytest.raises(InvalidRegionAmbiguityCaseError, match="mapping coordinate mismatch"):
        build_region_case(sheet, candidate, assessment)


@pytest.mark.parametrize(
    ("cells", "message"),
    [
        (
            (
                RegionCellCue("C9", "outside", "s", "", None, 1, 1),
                RegionCellCue("A1", "inside", "s", "", None, 1, 1),
            ),
            "outside source range",
        ),
        (
            (
                RegionCellCue("A1", "first", "s", "", None, 1, 1),
                RegionCellCue("A1", "second", "s", "", None, 1, 1),
            ),
            "duplicate cell coordinate",
        ),
        (
            (
                RegionCellCue("B2", "second", "s", "", None, 1, 1),
                RegionCellCue("A1", "first", "s", "", None, 1, 1),
            ),
            "row/column order",
        ),
        (
            (RegionCellCue("A1", "child", "s", "", "A1", 1, 1),),
            "merge children",
        ),
    ],
)
def test_direct_case_rejects_unsafe_cell_projection(cells, message: str):
    base = request_fixture()
    unsafe = RegionAmbiguityCase(
        case_id=base.case_id,
        sheet_name=base.sheet_name,
        sheet_visibility=base.sheet_visibility,
        source_range=base.source_range,
        fact_digest=base.fact_digest,
        cells=cells,
        feature_summary=base.feature_summary,
        choices=base.choices,
        fallback_choice_id=base.fallback_choice_id,
        ambiguity_codes=base.ambiguity_codes,
    )

    with pytest.raises(InvalidRegionAmbiguityCaseError, match=message):
        build_model_request(unsafe, ModelIdentity(provider="recording", model="fixture"))


@pytest.mark.parametrize(
    "invalid",
    [
        lambda case: replace(case, case_id="private malformed case id"),
        lambda case: replace(case, cells=list(case.cells)),
        lambda case: replace(case, choices=list(case.choices)),
        lambda case: replace(
            case,
            cells=(replace(case.cells[0], rowspan=True), *case.cells[1:]),
        ),
        lambda case: replace(
            case,
            choices=(replace(case.choices[0], local_score=float("inf")), *case.choices[1:]),
        ),
        lambda case: replace(case, ambiguity_codes=("private invalid code",)),
    ],
)
def test_direct_case_rejects_malformed_structural_fields_without_disclosure(invalid):
    case = invalid(request_fixture())

    with pytest.raises(InvalidRegionAmbiguityCaseError) as caught:
        build_model_request(case, ModelIdentity(provider="recording", model="fixture"))

    assert "private" not in str(caught.value)


def test_direct_case_normalizes_malformed_range_and_coordinate_errors():
    base = request_fixture()
    cases = (
        replace(base, source_range="private malformed range"),
        replace(
            base,
            cells=(replace(base.cells[0], coordinate="private coordinate"), *base.cells[1:]),
        ),
    )
    messages = []

    for case in cases:
        with pytest.raises(InvalidRegionAmbiguityCaseError) as caught:
            build_model_request(case, ModelIdentity(provider="recording", model="fixture"))
        messages.append(str(caught.value))

    assert messages[0] == messages[1]
    assert "private" not in messages[0]


def test_strict_reply_accepts_only_registered_choice_membership():
    request, choice = request_and_choice_fixture()
    reply = reply_for(
        request,
        {
            "case_id": request.case_ids[0],
            "status": "selected",
            "choice_id": choice.choice_id,
            "confidence": 0.91,
            "reason_codes": ["header_and_rows_are_consistent"],
        },
    )

    decision = decode_model_reply(reply, request, max_response_bytes=128_000)

    assert decision.case_id == request.case_ids[0]
    assert decision.choice_id == choice.choice_id
    assert decision.reported_confidence == 0.91


@pytest.mark.parametrize("duplicate_location", ["response", "decision"])
def test_strict_reply_rejects_duplicate_json_members_recursively(duplicate_location: str):
    request, choice = request_and_choice_fixture()
    checksum = json.dumps(request.request_checksum)
    case_id = json.dumps(request.case_ids[0])
    choice_id = json.dumps(choice.choice_id)
    choice_members = f'"choice_id":{choice_id}'
    if duplicate_location == "decision":
        choice_members = f'{choice_members},"choice_id":{choice_id}'
    decision = (
        f'{{"case_id":{case_id},"status":"selected",{choice_members},'
        '"confidence":0.91,"reason_codes":[]}'
    )
    checksum_members = f'"request_checksum":{checksum}'
    if duplicate_location == "response":
        checksum_members = f'{checksum_members},"request_checksum":{checksum}'
    reply = ProviderReply(
        body=(f'{{"schema_version":1,{checksum_members},"decisions":[{decision}]}}').encode(),
        provider_request_id=None,
    )

    with pytest.raises(WorkbookModelResponseError, match="duplicate JSON member"):
        decode_model_reply(reply, request, max_response_bytes=128_000)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown_top_level_field", "unknown response fields"),
        ("stale_checksum", "request checksum mismatch"),
        ("unknown_case", "unknown case_id"),
        ("unknown_choice", "unknown choice_id"),
        ("duplicate_decision", "duplicate decision"),
        ("missing_decision", "missing decision"),
        ("selected_without_choice", "selected decision requires choice_id"),
        ("abstained_with_choice", "abstained decision cannot include choice_id"),
    ],
)
def test_strict_reply_rejects_invalid_envelopes(mutation: str, message: str):
    request, reply = invalid_reply_fixture(mutation)

    with pytest.raises(WorkbookModelResponseError, match=message):
        decode_model_reply(reply, request, max_response_bytes=128_000)


@pytest.mark.parametrize(
    "confidence",
    [
        pytest.param(True, id="bool"),
        pytest.param(10**1000, id="huge_int"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="inf"),
        pytest.param(-0.01, id="below_zero"),
        pytest.param(1.01, id="above_one"),
    ],
)
def test_strict_reply_rejects_non_finite_or_out_of_range_confidence(confidence: float):
    request, choice = request_and_choice_fixture()
    reply = reply_for(
        request,
        {
            "case_id": request.case_ids[0],
            "status": "selected",
            "choice_id": choice.choice_id,
            "confidence": confidence,
            "reason_codes": [],
        },
    )

    with pytest.raises(WorkbookModelResponseError, match="confidence"):
        decode_model_reply(reply, request, max_response_bytes=128_000)


def test_reply_size_is_checked_before_json_decode():
    request, _ = request_and_choice_fixture()
    reply = ProviderReply(body=b"{" + b"x" * 128 + b"}", provider_request_id=None)

    with pytest.raises(WorkbookModelResponseError, match="response exceeds 64 bytes"):
        decode_model_reply(reply, request, max_response_bytes=64)


def test_memory_cache_stores_a_defensive_bytes_copy():
    cache = MemoryDecisionCache()
    body = bytearray(b"decision")

    cache.put("request", body)
    body[:] = b"mutated!"

    assert cache.get("request") == b"decision"
    assert cache.get("missing") is None


def test_build_region_case_rejects_invalid_local_membership():
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()

    with pytest.raises(InvalidRegionAmbiguityCaseError, match="ambiguous"):
        build_region_case(sheet, candidate, replace(assessment, ambiguous=False))
    with pytest.raises(InvalidRegionAmbiguityCaseError, match="duplicate choice_id"):
        build_region_case(
            sheet,
            candidate,
            replace(assessment, choices=(assessment.choices[0], assessment.choices[0])),
        )
    with pytest.raises(InvalidRegionAmbiguityCaseError, match="fallback"):
        build_region_case(
            sheet,
            candidate,
            replace(
                assessment,
                choices=(
                    assessment.choices[1],
                    RegionChoice("text-choice", "text", 0.4),
                ),
            ),
        )


def ambiguous_region_with_sensitive_facts():
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:C9")
    sheet.cells = {
        "A1": CellSnapshot(
            coordinate="A1",
            raw_value="Name",
            display_value="Name",
            data_type="s",
            style_id="header-style",
            comment="local comment",
            hyperlink="https://local-secret.example",
        ),
        "B2": CellSnapshot(
            coordinate="B2",
            raw_value=7,
            display_value="7",
            data_type="n",
            style_id="number-style",
        ),
        "C9": CellSnapshot(
            coordinate="C9",
            raw_value="do not send",
            display_value="do not send",
            formula="=SECRET()",
            comment="private comment",
            hyperlink="https://secret.example",
        ),
    }
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name="Data", range="A1:B2"),
        cell_refs=["B2", "A1"],
    )
    return sheet, candidate, assess_candidate_region(sheet, candidate)


def request_fixture():
    sheet, candidate, assessment = ambiguous_region_with_sensitive_facts()
    return build_region_case(sheet, candidate, assessment)


def request_checksum(case, model: str = "fixture") -> str:
    return build_model_request(
        case,
        ModelIdentity(provider="recording", model=model, revision="1"),
    ).request_checksum


def replace_cell_text(case, display_text: str):
    return replace(case, cells=(replace(case.cells[0], display_text=display_text), *case.cells[1:]))


def replace_choice_kind(case, kind: str):
    return replace(
        case,
        choices=(replace(case.choices[0], kind=kind), *case.choices[1:]),
    )


def request_and_choice_fixture():
    case = request_fixture()
    return (
        build_model_request(
            case, ModelIdentity(provider="recording", model="fixture", revision="1")
        ),
        case.choices[0],
    )


def reply_for(request, decision: dict[str, object]) -> ProviderReply:
    return ProviderReply(
        body=json.dumps(
            {
                "schema_version": 1,
                "request_checksum": request.request_checksum,
                "decisions": [decision],
            },
            separators=(",", ":"),
        ).encode(),
        provider_request_id="recording-1",
    )


def invalid_reply_fixture(mutation: str):
    request, choice = request_and_choice_fixture()
    decision = {
        "case_id": request.case_ids[0],
        "status": "selected",
        "choice_id": choice.choice_id,
        "confidence": 0.91,
        "reason_codes": [],
    }
    body: dict[str, object] = {
        "schema_version": 1,
        "request_checksum": request.request_checksum,
        "decisions": [decision],
    }
    if mutation == "unknown_top_level_field":
        body["patch"] = {}
    elif mutation == "stale_checksum":
        body["request_checksum"] = "sha256:stale"
    elif mutation == "unknown_case":
        decision["case_id"] = "other-case"
    elif mutation == "unknown_choice":
        decision["choice_id"] = "other-choice"
    elif mutation == "duplicate_decision":
        body["decisions"] = [decision, decision.copy()]
    elif mutation == "missing_decision":
        body["decisions"] = []
    elif mutation == "selected_without_choice":
        del decision["choice_id"]
    elif mutation == "abstained_with_choice":
        decision["status"] = "abstained"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    return request, ProviderReply(
        body=json.dumps(body, separators=(",", ":")).encode(),
        provider_request_id=None,
    )


def test_response_checksum_is_prefixed_sha256_digest():
    assert (
        response_checksum(b"reply")
        == "sha256:5782b18687e6cf8a482fc32d2db5b196d8821c458a0c069c6acf3953446e7bb5"
    )
