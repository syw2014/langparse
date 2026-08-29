from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langparse.workbooks.modeling.types import RegionChoice

_SAFE_TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_HEX64_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_RANGE_A1_PATTERN = re.compile(r"^[A-Za-z]+[1-9][0-9]*(?::[A-Za-z]+[1-9][0-9]*)?$")

VALID_SPLITS = frozenset({"tuning", "holdout"})
VALID_COHORTS = frozenset({"ambiguous", "clear_no_call"})
VALID_EXPECTED_KINDS = frozenset(
    {"logical_table", "form", "matrix", "text", "unclassified", "unresolvable"}
)


class WorkbookEvaluationError(Exception):
    """Base error for workbook ambiguity evaluation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "evaluation_error",
        evaluation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evaluation_id = evaluation_id

    def __str__(self) -> str:
        if self.evaluation_id:
            return f"[{self.code}] ({self.evaluation_id}): {super().__str__()}"
        return f"[{self.code}]: {super().__str__()}"


class InvalidGoldenSetError(WorkbookEvaluationError, ValueError):
    """Raised when golden set manifest, path, or hash is invalid."""


class GoldenSetDriftError(WorkbookEvaluationError, RuntimeError):
    """Raised when runtime cases, facts, or choices deviate from truth."""


@dataclass(frozen=True)
class GoldenCase:
    label_id: str
    sheet_name: str
    source_range: str
    expected: Literal["logical_table", "form", "matrix", "text", "unclassified", "unresolvable"]
    fact_digest: str
    choices_digest: str


@dataclass(frozen=True)
class GoldenSample:
    sample_id: str
    path: str
    sha256: str
    cohort: Literal["ambiguous", "clear_no_call"]
    cases: tuple[GoldenCase, ...]


@dataclass(frozen=True)
class GoldenSetManifest:
    schema_version: int
    dataset_id: str
    dataset_version: str
    split: Literal["tuning", "holdout"]
    source_root: Path
    samples: tuple[GoldenSample, ...]
    dataset_digest: str


def _strict_json_object_pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidGoldenSetError(
                f"Duplicate JSON key: {key}",
                code="invalid_schema",
            )
        result[key] = value
    return result


def compute_evaluation_id(
    dataset_id: str,
    dataset_version: str,
    sample_id: str,
    label_id: str,
) -> str:
    raw = f"{dataset_id}:{dataset_version}:{sample_id}:{label_id}".encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def compute_sample_evaluation_id(
    dataset_id: str,
    dataset_version: str,
    sample_id: str,
) -> str:
    raw = f"{dataset_id}:{dataset_version}:{sample_id}".encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def compute_choices_digest(choices: Iterable[RegionChoice]) -> str:
    payload = [
        {
            "choice_id": choice.choice_id,
            "kind": choice.kind,
            "local_score": round(float(choice.local_score), 6),
            "reason_codes": list(choice.reason_codes),
        }
        for choice in choices
    ]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def compute_dataset_digest(
    schema_version: int,
    dataset_id: str,
    dataset_version: str,
    split: str,
    samples: tuple[GoldenSample, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "split": split,
        "samples": [
            {
                "sample_id": sample.sample_id,
                "path": sample.path,
                "sha256": sample.sha256,
                "cohort": sample.cohort,
                "cases": [
                    {
                        "label_id": case.label_id,
                        "sheet_name": case.sheet_name,
                        "source_range": case.source_range,
                        "expected": case.expected,
                        "fact_digest": case.fact_digest,
                        "choices_digest": case.choices_digest,
                    }
                    for case in sample.cases
                ],
            }
            for sample in samples
        ],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def validate_output_dir_isolation(source_root: Path, output_dir: Path) -> None:
    resolved_root = source_root.resolve()
    resolved_output = output_dir.resolve()
    if resolved_output == resolved_root or resolved_output.is_relative_to(resolved_root):
        raise InvalidGoldenSetError(
            "Output directory must not be inside or equal to source root",
            code="input_output_overlap",
        )


def _validate_safe_token(token: object, field_name: str) -> str:
    if not isinstance(token, str) or not _SAFE_TOKEN_PATTERN.match(token):
        raise InvalidGoldenSetError(
            f"Invalid identifier for {field_name}: must be ASCII safe token (1..128 chars)",
            code="invalid_schema",
        )
    return token


def _validate_sha256(hash_str: object, field_name: str) -> str:
    if not isinstance(hash_str, str) or not _HEX64_PATTERN.match(hash_str):
        raise InvalidGoldenSetError(
            f"Invalid sha256 format for {field_name}: must be 'sha256:' followed by 64 lowercase hex characters",
            code="invalid_schema",
        )
    return hash_str


def _compute_file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def load_golden_set_manifest(manifest_path: str | Path) -> GoldenSetManifest:
    path = Path(manifest_path).resolve()
    if not path.is_file():
        raise InvalidGoldenSetError("Manifest file does not exist", code="file_not_found")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content, object_pairs_hook=_strict_json_object_pairs_hook)
    except json.JSONDecodeError as exc:
        raise InvalidGoldenSetError("Manifest is not valid JSON", code="invalid_schema") from exc

    if not isinstance(data, dict):
        raise InvalidGoldenSetError("Manifest root must be an object", code="invalid_schema")

    expected_manifest_keys = {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "split",
        "source_root",
        "samples",
    }
    if set(data.keys()) != expected_manifest_keys:
        raise InvalidGoldenSetError(
            "Manifest keys mismatch expected schema",
            code="invalid_schema",
        )

    schema_version = data["schema_version"]
    if type(schema_version) is not int or schema_version != 1 or isinstance(schema_version, bool):
        raise InvalidGoldenSetError(
            "schema_version must be integer 1",
            code="invalid_schema",
        )

    dataset_id = _validate_safe_token(data["dataset_id"], "dataset_id")
    dataset_version = _validate_safe_token(data["dataset_version"], "dataset_version")

    split = data["split"]
    if split not in VALID_SPLITS:
        raise InvalidGoldenSetError(
            f"split must be one of {sorted(VALID_SPLITS)}",
            code="invalid_schema",
        )

    source_root_str = data["source_root"]
    if not isinstance(source_root_str, str) or not source_root_str.strip():
        raise InvalidGoldenSetError("source_root must be a non-empty string", code="invalid_schema")
    if Path(source_root_str).is_absolute():
        raise InvalidGoldenSetError(
            "source_root must be relative to the manifest",
            code="path_traversal",
        )

    source_root = (path.parent / source_root_str).resolve()
    if not source_root.is_dir():
        raise InvalidGoldenSetError("source_root directory does not exist", code="file_not_found")

    samples_raw = data["samples"]
    if not isinstance(samples_raw, list):
        raise InvalidGoldenSetError("samples must be a list", code="invalid_schema")

    expected_sample_keys = {"sample_id", "path", "sha256", "cohort", "cases"}
    expected_case_keys = {
        "label_id",
        "sheet_name",
        "source_range",
        "expected",
        "fact_digest",
        "choices_digest",
    }

    seen_sample_ids: set[str] = set()
    samples: list[GoldenSample] = []

    for sample_dict in samples_raw:
        if not isinstance(sample_dict, dict) or set(sample_dict.keys()) != expected_sample_keys:
            raise InvalidGoldenSetError(
                "Sample entry keys mismatch schema",
                code="invalid_schema",
            )

        sample_id = _validate_safe_token(sample_dict["sample_id"], "sample_id")
        if sample_id in seen_sample_ids:
            raise InvalidGoldenSetError(
                f"Duplicate sample_id: {sample_id}",
                code="duplicate_id",
            )
        seen_sample_ids.add(sample_id)

        sample_rel_path = sample_dict["path"]
        if not isinstance(sample_rel_path, str) or not sample_rel_path.strip():
            raise InvalidGoldenSetError(
                "Sample path must be a non-empty string", code="invalid_schema"
            )

        if Path(sample_rel_path).is_absolute() or ".." in Path(sample_rel_path).parts:
            raise InvalidGoldenSetError(
                "Sample path must be relative and not contain '..'",
                code="path_traversal",
            )

        full_sample_path = (source_root / sample_rel_path).resolve()
        if not full_sample_path.is_relative_to(source_root):
            raise InvalidGoldenSetError(
                "Sample path resolves outside source_root",
                code="path_traversal",
            )

        if not full_sample_path.is_file():
            raise InvalidGoldenSetError("Sample file does not exist", code="file_not_found")

        expected_sha256 = _validate_sha256(sample_dict["sha256"], "sample sha256")
        actual_sha256 = _compute_file_sha256(full_sample_path)
        if actual_sha256 != expected_sha256:
            raise InvalidGoldenSetError(
                "Sample file SHA-256 does not match manifest",
                code="hash_mismatch",
            )

        cohort = sample_dict["cohort"]
        if cohort not in VALID_COHORTS:
            raise InvalidGoldenSetError(
                f"cohort must be one of {sorted(VALID_COHORTS)}",
                code="invalid_schema",
            )

        cases_raw = sample_dict["cases"]
        if not isinstance(cases_raw, list):
            raise InvalidGoldenSetError("cases must be a list", code="invalid_schema")

        if cohort == "clear_no_call" and len(cases_raw) != 0:
            raise InvalidGoldenSetError(
                "clear_no_call cohort must have empty cases",
                code="invalid_schema",
            )
        if cohort == "ambiguous" and len(cases_raw) == 0:
            raise InvalidGoldenSetError(
                "ambiguous cohort must have at least one case",
                code="invalid_schema",
            )

        seen_label_ids: set[str] = set()
        cases: list[GoldenCase] = []
        for case_dict in cases_raw:
            if not isinstance(case_dict, dict) or set(case_dict.keys()) != expected_case_keys:
                raise InvalidGoldenSetError(
                    "Case entry keys mismatch schema",
                    code="invalid_schema",
                )

            label_id = _validate_safe_token(case_dict["label_id"], "label_id")
            if label_id in seen_label_ids:
                raise InvalidGoldenSetError(
                    f"Duplicate label_id in sample: {label_id}",
                    code="duplicate_id",
                )
            seen_label_ids.add(label_id)

            sheet_name = case_dict["sheet_name"]
            if not isinstance(sheet_name, str) or not sheet_name.strip():
                raise InvalidGoldenSetError(
                    "sheet_name must be non-empty string", code="invalid_schema"
                )

            source_range = case_dict["source_range"]
            if not isinstance(source_range, str) or not _RANGE_A1_PATTERN.match(source_range):
                raise InvalidGoldenSetError(
                    "source_range must be standard A1 format", code="invalid_schema"
                )

            expected = case_dict["expected"]
            if expected not in VALID_EXPECTED_KINDS:
                raise InvalidGoldenSetError(
                    f"expected must be one of {sorted(VALID_EXPECTED_KINDS)}",
                    code="invalid_schema",
                )

            fact_digest = _validate_sha256(case_dict["fact_digest"], "fact_digest")
            choices_digest = _validate_sha256(case_dict["choices_digest"], "choices_digest")

            cases.append(
                GoldenCase(
                    label_id=label_id,
                    sheet_name=sheet_name,
                    source_range=source_range,
                    expected=expected,
                    fact_digest=fact_digest,
                    choices_digest=choices_digest,
                )
            )

        samples.append(
            GoldenSample(
                sample_id=sample_id,
                path=sample_rel_path,
                sha256=expected_sha256,
                cohort=cohort,
                cases=tuple(cases),
            )
        )

    samples_tuple = tuple(samples)
    dataset_digest = compute_dataset_digest(
        schema_version=schema_version,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        split=split,
        samples=samples_tuple,
    )

    return GoldenSetManifest(
        schema_version=schema_version,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        split=split,
        source_root=source_root,
        samples=samples_tuple,
        dataset_digest=dataset_digest,
    )
