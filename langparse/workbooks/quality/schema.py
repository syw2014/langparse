from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_QUALITY_METRICS = frozenset(
    {
        "block_precision",
        "block_recall",
        "header_path_accuracy",
        "row_role_f1",
        "form_field_exact_match",
        "matrix_axis_accuracy",
        "continuation_precision",
        "continuation_recall",
        "source_ref_completeness",
        "source_ref_validity_ratio",
        "cell_coverage_ratio",
        "fallback_rate",
        "object_fact_precision",
        "object_fact_recall",
        "object_semantic_recall",
    }
)
_SOURCE_REF_PATTERN = re.compile(r"^[^!]+![A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?$")
_CELL_RANGE_PATTERN = re.compile(r"^[A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?$")
_BLOCK_KINDS = frozenset(
    {"logical_table", "form", "matrix", "text", "unclassified", "chart", "image"}
)
_ROW_ROLES = frozenset(
    {
        "title",
        "context",
        "header",
        "repeated_title",
        "repeated_context",
        "repeated_header",
        "section_header",
        "data",
        "total",
        "unknown",
    }
)
_OBJECT_KINDS = frozenset({"chart", "image"})
_SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class WorkbookQualityManifestError(ValueError):
    """Raised when a workbook quality manifest cannot be trusted."""


@dataclass(frozen=True)
class HeaderTruth:
    coordinate: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class RowTruth:
    source_range: str
    role: str


@dataclass(frozen=True)
class MatrixAxesTruth:
    rows: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class BlockTruth:
    source_range: str
    kind: str
    headers: tuple[HeaderTruth, ...]
    rows: tuple[RowTruth, ...]
    form_fields: tuple[tuple[str, Any], ...]
    matrix_axes: MatrixAxesTruth


@dataclass(frozen=True)
class SheetTruth:
    name: str
    blocks: tuple[BlockTruth, ...]


@dataclass(frozen=True)
class ObjectTruth:
    sheet_name: str
    kind: str
    anchor: str


@dataclass(frozen=True)
class WorkbookExpectation:
    sheets: tuple[SheetTruth, ...]
    continuations: tuple[tuple[str, ...], ...]
    required_source_refs: tuple[str, ...]
    objects: tuple[ObjectTruth, ...]


@dataclass(frozen=True)
class WorkbookQualitySample:
    sample_id: str
    path: str
    sha256: str
    expectation: WorkbookExpectation


@dataclass(frozen=True)
class WorkbookQualityGate:
    minimum: dict[str, float]
    maximum: dict[str, float]


@dataclass(frozen=True)
class WorkbookQualityManifest:
    schema_version: int
    dataset_id: str
    dataset_version: str
    split: str
    source_root: Path
    quality_gate: WorkbookQualityGate
    samples: tuple[WorkbookQualitySample, ...]
    dataset_digest: str


def load_workbook_quality_manifest(path: str | Path) -> WorkbookQualityManifest:
    manifest_path = Path(path).resolve()
    try:
        data = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object_pairs,
        )
    except json.JSONDecodeError as exc:
        raise WorkbookQualityManifestError("Manifest is not valid JSON") from exc
    _require_keys(
        data,
        {
            "schema_version",
            "dataset_id",
            "dataset_version",
            "split",
            "source_root",
            "quality_gate",
            "samples",
        },
        "Manifest",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise WorkbookQualityManifestError("schema_version must be integer 1")
    _safe_token(data["dataset_id"], "dataset_id")
    _safe_token(data["dataset_version"], "dataset_version")
    if not isinstance(data["split"], str) or data["split"] not in {
        "tuning",
        "holdout",
    }:
        raise WorkbookQualityManifestError("split must be tuning or holdout")
    quality_gate = data["quality_gate"]
    _require_keys(quality_gate, {"minimum", "maximum"}, "Quality gate")
    if not isinstance(quality_gate["minimum"], dict) or not isinstance(
        quality_gate["maximum"], dict
    ):
        raise WorkbookQualityManifestError("Quality gate thresholds must be objects")
    gate_names = set(quality_gate["minimum"]) | set(quality_gate["maximum"])
    unknown_metrics = sorted(gate_names - _QUALITY_METRICS)
    if unknown_metrics:
        raise WorkbookQualityManifestError(f"Unknown quality metric: {', '.join(unknown_metrics)}")
    for threshold in (*quality_gate["minimum"].values(), *quality_gate["maximum"].values()):
        if type(threshold) not in {int, float} or not 0.0 <= threshold <= 1.0:
            raise WorkbookQualityManifestError(
                "Quality gate threshold must be a number between 0 and 1"
            )
    source_root_value = data["source_root"]
    if (
        not isinstance(source_root_value, str)
        or not source_root_value
        or Path(source_root_value).is_absolute()
        or ".." in Path(source_root_value).parts
    ):
        raise WorkbookQualityManifestError("source_root must be a safe relative path")
    source_root = (manifest_path.parent / source_root_value).resolve()
    if not source_root.is_dir():
        raise WorkbookQualityManifestError("source_root directory does not exist")
    if not isinstance(data["samples"], list):
        raise WorkbookQualityManifestError("samples must be a list")
    samples = tuple(_load_sample(source_root, item) for item in data["samples"])
    sample_ids = [sample.sample_id for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise WorkbookQualityManifestError("Duplicate sample_id")
    if not samples:
        raise WorkbookQualityManifestError("Manifest must contain at least one sample")
    if not gate_names:
        raise WorkbookQualityManifestError("Quality gate must contain at least one threshold")
    return WorkbookQualityManifest(
        schema_version=data["schema_version"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        split=data["split"],
        source_root=source_root,
        quality_gate=WorkbookQualityGate(
            minimum=dict(data["quality_gate"]["minimum"]),
            maximum=dict(data["quality_gate"]["maximum"]),
        ),
        samples=samples,
        dataset_digest=_canonical_digest(data),
    )


def _require_keys(data: object, expected: set[str], label: str) -> None:
    if not isinstance(data, dict) or set(data) != expected:
        raise WorkbookQualityManifestError(f"{label} keys do not match schema")


def _safe_token(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_PATTERN.fullmatch(value) is None:
        raise WorkbookQualityManifestError(f"{field_name} must be a safe identifier")
    return value


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkbookQualityManifestError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_digest(data: dict[str, Any]) -> str:
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_sample(source_root: Path, data: dict[str, Any]) -> WorkbookQualitySample:
    _require_keys(data, {"sample_id", "path", "sha256", "expectation"}, "Sample")
    sample_id = _safe_token(data["sample_id"], "sample_id")
    sample_value = data["path"]
    if not isinstance(sample_value, str) or not sample_value or Path(sample_value).is_absolute():
        raise WorkbookQualityManifestError("Sample path must be a non-empty relative path")
    if not isinstance(data["sha256"], str) or _SHA256_PATTERN.fullmatch(data["sha256"]) is None:
        raise WorkbookQualityManifestError("Sample sha256 has invalid format")
    sample_path = (source_root / sample_value).resolve()
    if not sample_path.is_relative_to(source_root):
        raise WorkbookQualityManifestError("Sample path resolves outside source_root")
    if not sample_path.is_file():
        raise WorkbookQualityManifestError("Sample file does not exist")
    actual_hash = f"sha256:{hashlib.sha256(sample_path.read_bytes()).hexdigest()}"
    if actual_hash != data["sha256"]:
        raise WorkbookQualityManifestError("Sample file SHA-256 does not match manifest")
    return WorkbookQualitySample(
        sample_id=sample_id,
        path=sample_value,
        sha256=data["sha256"],
        expectation=_load_expectation(data["expectation"]),
    )


def _load_expectation(data: dict[str, Any]) -> WorkbookExpectation:
    _require_keys(
        data,
        {"sheets", "continuations", "required_source_refs", "objects"},
        "Expectation",
    )
    sheets_data = _require_list(data["sheets"], "Expectation sheets")
    continuations_data = _require_list(data["continuations"], "Expectation continuations")
    required_refs_data = _require_list(
        data["required_source_refs"], "Expectation required_source_refs"
    )
    objects_data = _require_list(data["objects"], "Expectation objects")
    continuations: list[tuple[str, ...]] = []
    for group in continuations_data:
        refs = _require_list(group, "Continuation group")
        if len(refs) < 2:
            raise WorkbookQualityManifestError(
                "Continuation group must contain at least two source refs"
            )
        if any(
            not isinstance(ref, str) or _SOURCE_REF_PATTERN.fullmatch(ref) is None for ref in refs
        ):
            raise WorkbookQualityManifestError("Invalid source ref")
        if len(refs) != len(set(refs)):
            raise WorkbookQualityManifestError("Continuation group contains duplicate source refs")
        continuations.append(tuple(refs))
    if len(continuations) != len(set(continuations)):
        raise WorkbookQualityManifestError("Duplicate continuation group")
    continuation_members: set[str] = set()
    for group in continuations:
        overlap = continuation_members.intersection(group)
        if overlap:
            raise WorkbookQualityManifestError(
                "Continuation groups contain overlapping source refs"
            )
        continuation_members.update(group)
    required_source_refs = tuple(required_refs_data)
    continuation_refs = tuple(ref for group in continuations for ref in group)
    if any(
        not isinstance(ref, str) or _SOURCE_REF_PATTERN.fullmatch(ref) is None
        for ref in (*required_source_refs, *continuation_refs)
    ):
        raise WorkbookQualityManifestError("Invalid source ref")
    sheets = tuple(_load_sheet(item) for item in sheets_data)
    objects = tuple(_load_object(item) for item in objects_data)
    sheet_names = [sheet.name for sheet in sheets]
    if len(sheet_names) != len(set(sheet_names)):
        raise WorkbookQualityManifestError("Duplicate sheet name")
    block_truth_keys = [
        (sheet.name, block.source_range, block.kind) for sheet in sheets for block in sheet.blocks
    ]
    if len(block_truth_keys) != len(set(block_truth_keys)):
        raise WorkbookQualityManifestError("Duplicate block truth")
    expected_block_refs = {
        f"{sheet.name}!{block.source_range}" for sheet in sheets for block in sheet.blocks
    }
    if any(ref not in expected_block_refs for group in continuations for ref in group):
        raise WorkbookQualityManifestError(
            "Continuation source ref must identify an expected block"
        )
    if any(item.sheet_name not in sheet_names for item in objects):
        raise WorkbookQualityManifestError("Object sheet_name must identify an expected sheet")
    if len(objects) != len(set(objects)):
        raise WorkbookQualityManifestError("Duplicate object truth")
    if len(required_source_refs) != len(set(required_source_refs)):
        raise WorkbookQualityManifestError("Duplicate required_source_ref")
    if any(_source_ref_sheet(ref) not in sheet_names for ref in required_source_refs):
        raise WorkbookQualityManifestError("Required source ref must identify an expected sheet")
    return WorkbookExpectation(
        sheets=sheets,
        continuations=tuple(continuations),
        required_source_refs=required_source_refs,
        objects=objects,
    )


def _load_sheet(data: dict[str, Any]) -> SheetTruth:
    _require_keys(data, {"name", "blocks"}, "Sheet")
    name = _require_non_empty_string(data["name"], "Sheet name")
    blocks = _require_list(data["blocks"], "Sheet blocks")
    return SheetTruth(name=name, blocks=tuple(_load_block(item) for item in blocks))


def _load_block(data: dict[str, Any]) -> BlockTruth:
    _require_keys(
        data,
        {"source_range", "kind", "headers", "rows", "form_fields", "matrix_axes"},
        "Block",
    )
    source_range = _require_cell_range(data["source_range"], "Block source_range")
    if not isinstance(data["kind"], str) or data["kind"] not in _BLOCK_KINDS:
        raise WorkbookQualityManifestError("Unknown block kind")
    headers = _require_list(data["headers"], "Block headers")
    rows = _require_list(data["rows"], "Block rows")
    form_fields = _require_list(data["form_fields"], "Block form_fields")
    matrix_axes = data["matrix_axes"]
    _require_keys(matrix_axes, {"rows", "columns"}, "Matrix axes")
    matrix_rows = _require_string_list(matrix_axes["rows"], "Matrix axes rows")
    matrix_columns = _require_string_list(matrix_axes["columns"], "Matrix axes columns")
    header_truth = tuple(_load_header(item) for item in headers)
    if len(header_truth) != len(set(header_truth)):
        raise WorkbookQualityManifestError("Duplicate header truth")
    row_truth = tuple(_load_row(item) for item in rows)
    if len(row_truth) != len(set(row_truth)):
        raise WorkbookQualityManifestError("Duplicate row truth")
    return BlockTruth(
        source_range=source_range,
        kind=data["kind"],
        headers=header_truth,
        rows=row_truth,
        form_fields=tuple(_load_form_field(item) for item in form_fields),
        matrix_axes=MatrixAxesTruth(
            rows=matrix_rows,
            columns=matrix_columns,
        ),
    )


def _load_header(data: dict[str, Any]) -> HeaderTruth:
    _require_keys(data, {"coordinate", "path"}, "Header")
    coordinate = _require_non_empty_string(data["coordinate"], "Header coordinate")
    path = _require_string_list(data["path"], "Header path")
    return HeaderTruth(coordinate=coordinate, path=path)


def _load_row(data: dict[str, Any]) -> RowTruth:
    _require_keys(data, {"source_range", "role"}, "Row")
    role = _require_non_empty_string(data["role"], "Row role")
    if role not in _ROW_ROLES:
        raise WorkbookQualityManifestError("Unknown row role")
    return RowTruth(
        source_range=_require_cell_range(data["source_range"], "Row source_range"),
        role=role,
    )


def _load_form_field(data: dict[str, Any]) -> tuple[str, Any]:
    _require_keys(data, {"label", "value"}, "Form field")
    return _require_non_empty_string(data["label"], "Form field label"), data["value"]


def _load_object(data: dict[str, Any]) -> ObjectTruth:
    _require_keys(data, {"sheet_name", "kind", "anchor"}, "Object")
    kind = _require_non_empty_string(data["kind"], "Object kind")
    if kind not in _OBJECT_KINDS:
        raise WorkbookQualityManifestError("Unknown object kind")
    return ObjectTruth(
        sheet_name=_require_non_empty_string(data["sheet_name"], "Object sheet_name"),
        kind=kind,
        anchor=_require_cell_range(data["anchor"], "Object anchor"),
    )


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkbookQualityManifestError(f"{label} must be a list")
    return value


def _require_string_list(value: object, label: str) -> tuple[str, ...]:
    items = _require_list(value, label)
    if any(not isinstance(item, str) for item in items):
        raise WorkbookQualityManifestError(f"{label} must contain only strings")
    return tuple(items)


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkbookQualityManifestError(f"{label} must be a non-empty string")
    return value


def _require_cell_range(value: object, label: str) -> str:
    if not isinstance(value, str) or _CELL_RANGE_PATTERN.fullmatch(value) is None:
        raise WorkbookQualityManifestError(f"{label} must be an A1 cell range")
    return value


def _source_ref_sheet(value: str) -> str:
    sheet_name = value.rsplit("!", 1)[0]
    if len(sheet_name) >= 2 and sheet_name.startswith("'") and sheet_name.endswith("'"):
        return sheet_name[1:-1].replace("''", "'")
    return sheet_name
