from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.utils.cell import coordinate_to_tuple

from langparse.workbooks.classification import RegionAssessment
from langparse.workbooks.types import CandidateRegion, CellSnapshot, SheetSnapshot, stable_id

from .ports import InvalidRegionAmbiguityCaseError, WorkbookModelResponseError
from .types import (
    REGION_PROMPT_VERSION,
    REGION_RULE_VERSION,
    REGION_SCHEMA_VERSION,
    REGION_VALIDATOR_VERSION,
    ModelIdentity,
    ProviderReply,
    RegionAmbiguityCase,
    RegionCellCue,
    RegionChoice,
    RegionFeatureScalar,
    RegionModelDecision,
    WorkbookModelRequest,
)


def build_region_case(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
    assessment: RegionAssessment,
) -> RegionAmbiguityCase:
    """Project one ambiguous region into the privacy-preserving model contract."""

    if not assessment.ambiguous:
        raise InvalidRegionAmbiguityCaseError("assessment must be ambiguous")
    if candidate.source_ref.sheet_name != sheet.name:
        raise InvalidRegionAmbiguityCaseError("candidate source sheet does not match sheet")
    if sheet.visibility != "visible":
        raise InvalidRegionAmbiguityCaseError("hidden sheet content cannot be sent")

    _validate_candidate_coordinates(candidate)
    _validate_choices(assessment.choices, assessment.deterministic.kind)

    cells = tuple(
        _cell_cue(cell)
        for coordinate in _ordered_candidate_coordinates(candidate)
        if (cell := sheet.cells.get(coordinate)) is not None
        and _is_safe_visible_occupied_cell(sheet, cell)
    )
    feature_summary = _feature_summary(assessment)
    choices = tuple(assessment.choices)
    fallback_choice_id = next(
        choice.choice_id for choice in choices if choice.kind == assessment.deterministic.kind
    )
    fact_digest = _digest(
        {
            "sheet_name": sheet.name,
            "sheet_visibility": sheet.visibility,
            "source_range": candidate.source_ref.range,
            "cells": [_cue_payload(cell) for cell in cells],
            "feature_summary": dict(feature_summary),
            "choices": [_choice_payload(choice) for choice in choices],
            "region_rule_version": REGION_RULE_VERSION,
            "region_validator_version": REGION_VALIDATOR_VERSION,
        }
    )
    return RegionAmbiguityCase(
        case_id=stable_id("region_case", REGION_RULE_VERSION, candidate.source_ref.key),
        sheet_name=sheet.name,
        sheet_visibility=sheet.visibility,
        source_range=candidate.source_ref.range,
        fact_digest=fact_digest,
        cells=cells,
        feature_summary=feature_summary,
        choices=choices,
        fallback_choice_id=fallback_choice_id,
        ambiguity_codes=tuple(assessment.ambiguity_codes),
    )


def build_model_request(case: RegionAmbiguityCase, identity: ModelIdentity) -> WorkbookModelRequest:
    """Build the one-case Phase 4A request with a canonical checksum."""

    _validate_case(case)
    request_case = {
        "case_id": case.case_id,
        "sheet_name": case.sheet_name,
        "sheet_visibility": case.sheet_visibility,
        "source_range": case.source_range,
        "fact_digest": case.fact_digest,
        "feature_summary": dict(case.feature_summary),
        "cells": [_cue_payload(cell) for cell in case.cells],
        "choices": [_choice_payload(choice) for choice in case.choices],
        "fallback_choice_id": case.fallback_choice_id,
        "ambiguity_codes": list(case.ambiguity_codes),
    }
    envelope: dict[str, object] = {
        "schema_version": REGION_SCHEMA_VERSION,
        "prompt_version": REGION_PROMPT_VERSION,
        "model_identity": {
            "provider": identity.provider,
            "model": identity.model,
            "revision": identity.revision,
        },
        "cases": [request_case],
    }
    request_checksum = _digest(envelope)
    body = _canonical_json({**envelope, "request_checksum": request_checksum})
    return WorkbookModelRequest(
        schema_version=REGION_SCHEMA_VERSION,
        prompt_version=REGION_PROMPT_VERSION,
        request_checksum=request_checksum,
        body=body,
        case_ids=(case.case_id,),
        choice_ids_by_case=((case.case_id, tuple(choice.choice_id for choice in case.choices)),),
    )


def decode_model_reply(
    reply: ProviderReply,
    request: WorkbookModelRequest,
    *,
    max_response_bytes: int,
) -> RegionModelDecision:
    """Decode a provider reply only when it exactly matches the local contract."""

    if len(reply.body) > max_response_bytes:
        raise WorkbookModelResponseError(f"response exceeds {max_response_bytes} bytes")
    try:
        payload = json.loads(reply.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkbookModelResponseError("response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise WorkbookModelResponseError("response must be a JSON object")
    _exact_keys(
        payload,
        {"schema_version", "request_checksum", "decisions"},
        "response",
    )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != REGION_SCHEMA_VERSION
    ):
        raise WorkbookModelResponseError("unsupported response schema_version")
    if not isinstance(payload["request_checksum"], str):
        raise WorkbookModelResponseError("request_checksum must be a string")
    if payload["request_checksum"] != request.request_checksum:
        raise WorkbookModelResponseError("request checksum mismatch")

    decisions = payload["decisions"]
    if not isinstance(decisions, list):
        raise WorkbookModelResponseError("decisions must be a list")
    membership = _request_membership(request)
    expected_case_ids = set(request.case_ids)
    decoded: dict[str, RegionModelDecision] = {}
    for raw_decision in decisions:
        decision = _decode_decision(raw_decision, membership)
        if decision.case_id not in expected_case_ids:
            raise WorkbookModelResponseError("unknown case_id")
        if decision.case_id in decoded:
            raise WorkbookModelResponseError("duplicate decision")
        decoded[decision.case_id] = decision

    missing_case_ids = expected_case_ids - decoded.keys()
    if missing_case_ids:
        raise WorkbookModelResponseError("missing decision")
    if len(decoded) != len(request.case_ids):
        raise WorkbookModelResponseError("response must contain one decision per request case")
    if len(request.case_ids) != 1:
        raise WorkbookModelResponseError("Phase 4A requests require exactly one case")
    return decoded[request.case_ids[0]]


def response_checksum(body: bytes) -> str:
    return _digest_bytes(body)


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: dict[str, object]) -> str:
    return _digest_bytes(_canonical_json(payload))


def _digest_bytes(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def _validate_candidate_coordinates(candidate: CandidateRegion) -> None:
    min_column, min_row, max_column, max_row = range_boundaries(candidate.source_ref.range)
    for coordinate in candidate.cell_refs:
        try:
            row, column = coordinate_to_tuple(coordinate)
        except ValueError as error:
            raise InvalidRegionAmbiguityCaseError(
                f"invalid candidate cell: {coordinate}"
            ) from error
        if not min_row <= row <= max_row or not min_column <= column <= max_column:
            raise InvalidRegionAmbiguityCaseError("candidate contains cell outside source range")


def _validate_choices(choices: tuple[RegionChoice, ...], fallback_kind: str) -> None:
    choice_ids = [choice.choice_id for choice in choices]
    if len(set(choice_ids)) != len(choice_ids):
        raise InvalidRegionAmbiguityCaseError("duplicate choice_id")
    choice_kinds = {choice.kind for choice in choices}
    if len(choice_kinds) < 2:
        raise InvalidRegionAmbiguityCaseError(
            "ambiguous assessment requires at least two choice kinds"
        )
    if fallback_kind not in choice_kinds:
        raise InvalidRegionAmbiguityCaseError("fallback choice is not registered")


def _ordered_candidate_coordinates(candidate: CandidateRegion) -> tuple[str, ...]:
    return tuple(sorted(set(candidate.cell_refs), key=coordinate_to_tuple))


def _is_safe_visible_occupied_cell(sheet: SheetSnapshot, cell: CellSnapshot) -> bool:
    row, column = coordinate_to_tuple(cell.coordinate)
    return (
        cell.merge_anchor is None
        and not cell.hidden
        and row not in sheet.hidden_rows
        and get_column_letter(column) not in sheet.hidden_columns
        and any(
            (
                cell.raw_value is not None,
                cell.display_value != "",
                cell.formula is not None,
                cell.comment is not None,
                cell.hyperlink is not None,
            )
        )
    )


def _cell_cue(cell: CellSnapshot) -> RegionCellCue:
    return RegionCellCue(
        coordinate=cell.coordinate,
        display_text=cell.display_value,
        value_type=cell.data_type,
        style_fingerprint=cell.style_id,
        merge_anchor=cell.merge_anchor,
        rowspan=cell.rowspan,
        colspan=cell.colspan,
    )


def _feature_summary(assessment: RegionAssessment) -> tuple[tuple[str, RegionFeatureScalar], ...]:
    summary: list[tuple[str, RegionFeatureScalar]] = []
    for feature in fields(assessment.deterministic.features):
        value = getattr(assessment.deterministic.features, feature.name)
        if value is None or type(value) in (str, int, float, bool):
            summary.append((feature.name, value))
    return tuple(summary)


def _cue_payload(cell: RegionCellCue) -> dict[str, object]:
    return {
        "coordinate": cell.coordinate,
        "display_text": cell.display_text,
        "value_type": cell.value_type,
        "style_fingerprint": cell.style_fingerprint,
        "merge_anchor": cell.merge_anchor,
        "rowspan": cell.rowspan,
        "colspan": cell.colspan,
    }


def _choice_payload(choice: RegionChoice) -> dict[str, object]:
    return {
        "choice_id": choice.choice_id,
        "kind": choice.kind,
        "local_score": choice.local_score,
        "reason_codes": list(choice.reason_codes),
    }


def _validate_case(case: RegionAmbiguityCase) -> None:
    if case.sheet_visibility != "visible":
        raise InvalidRegionAmbiguityCaseError("hidden sheet content cannot be sent")
    _validate_choices(case.choices, _fallback_kind(case))
    if case.fallback_choice_id not in {choice.choice_id for choice in case.choices}:
        raise InvalidRegionAmbiguityCaseError("fallback choice is not registered")


def _fallback_kind(case: RegionAmbiguityCase) -> str:
    for choice in case.choices:
        if choice.choice_id == case.fallback_choice_id:
            return choice.kind
    raise InvalidRegionAmbiguityCaseError("fallback choice is not registered")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    if unknown:
        raise WorkbookModelResponseError(f"unknown {label} fields")
    missing = expected - set(value)
    if missing:
        raise WorkbookModelResponseError(f"missing {label} fields")


def _request_membership(request: WorkbookModelRequest) -> Mapping[str, tuple[str, ...]]:
    membership = dict(request.choice_ids_by_case)
    if set(membership) != set(request.case_ids) or len(membership) != len(request.case_ids):
        raise WorkbookModelResponseError("invalid local request membership registry")
    return membership


def _decode_decision(
    value: object,
    membership: Mapping[str, tuple[str, ...]],
) -> RegionModelDecision:
    if not isinstance(value, dict):
        raise WorkbookModelResponseError("decision must be an object")
    if "status" not in value or not isinstance(value["status"], str):
        raise WorkbookModelResponseError("decision status must be a string")
    status = value["status"]
    expected = {"case_id", "status", "confidence", "reason_codes"}
    if status == "selected":
        if "choice_id" not in value:
            raise WorkbookModelResponseError("selected decision requires choice_id")
        expected.add("choice_id")
    elif status == "abstained" and "choice_id" in value:
        raise WorkbookModelResponseError("abstained decision cannot include choice_id")
    _exact_keys(value, expected, "decision")
    case_id = value["case_id"]
    if not isinstance(case_id, str):
        raise WorkbookModelResponseError("case_id must be a string")
    if status not in {"selected", "abstained"}:
        raise WorkbookModelResponseError("unknown decision status")
    confidence = value["confidence"]
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise WorkbookModelResponseError("confidence must be finite and between 0 and 1")
    reason_codes = value["reason_codes"]
    if not isinstance(reason_codes, list) or not all(
        isinstance(code, str) for code in reason_codes
    ):
        raise WorkbookModelResponseError("reason_codes must be a list of strings")
    if status == "abstained":
        return RegionModelDecision(
            case_id=case_id,
            status="abstained",
            choice_id=None,
            reported_confidence=float(confidence),
            reason_codes=tuple(reason_codes),
        )
    choice_id = value["choice_id"]
    if not isinstance(choice_id, str):
        raise WorkbookModelResponseError("choice_id must be a string")
    if case_id not in membership:
        raise WorkbookModelResponseError("unknown case_id")
    if choice_id not in membership[case_id]:
        raise WorkbookModelResponseError("unknown choice_id")
    return RegionModelDecision(
        case_id=case_id,
        status="selected",
        choice_id=choice_id,
        reported_confidence=float(confidence),
        reason_codes=tuple(reason_codes),
    )
