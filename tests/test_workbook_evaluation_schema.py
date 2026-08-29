from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from langparse.workbooks.evaluation.schema import (
    GoldenSetManifest,
    InvalidGoldenSetError,
    compute_choices_digest,
    compute_evaluation_id,
    load_golden_set_manifest,
    validate_output_dir_isolation,
)
from langparse.workbooks.modeling.types import RegionChoice


def _sha256_prefixed(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _make_dummy_file(
    directory: Path, name: str, content: bytes = b"dummy content"
) -> tuple[Path, str]:
    file_path = directory / name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path, _sha256_prefixed(content)


def test_valid_manifest_loading(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    f1, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"sample1_bytes")
    f2, hash2 = _make_dummy_file(source_root, "sample2.xlsx", b"sample2_bytes")

    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset-01",
        "dataset_version": "v1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": hash1,
                "cohort": "ambiguous",
                "cases": [
                    {
                        "label_id": "case-01",
                        "sheet_name": "Sheet1",
                        "source_range": "A1:B10",
                        "expected": "text",
                        "fact_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                        "choices_digest": "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
                    }
                ],
            },
            {
                "sample_id": "sample-02",
                "path": "sample2.xlsx",
                "sha256": hash2,
                "cohort": "clear_no_call",
                "cases": [],
            },
        ],
    }

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")

    manifest = load_golden_set_manifest(manifest_path)
    assert isinstance(manifest, GoldenSetManifest)
    assert manifest.schema_version == 1
    assert manifest.dataset_id == "test-dataset-01"
    assert manifest.dataset_version == "v1"
    assert manifest.split == "tuning"
    assert manifest.source_root == source_root.resolve()
    assert len(manifest.samples) == 2
    assert manifest.samples[0].sample_id == "sample-01"
    assert manifest.samples[0].cohort == "ambiguous"
    assert len(manifest.samples[0].cases) == 1
    assert manifest.samples[0].cases[0].label_id == "case-01"
    assert manifest.samples[1].cohort == "clear_no_call"
    assert manifest.dataset_digest.startswith("sha256:")
    assert len(manifest.dataset_digest) == 71


def test_reject_duplicate_json_keys(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"content")

    # JSON with duplicate key "split"
    raw_json = f"""{{
        "schema_version": 1,
        "dataset_id": "test-dup",
        "dataset_version": "1",
        "split": "tuning",
        "split": "holdout",
        "source_root": "fixtures",
        "samples": [
            {{
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": "{hash1}",
                "cohort": "clear_no_call",
                "cases": []
            }}
        ]
    }}"""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(raw_json, encoding="utf-8")

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"


def test_reject_unknown_fields(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"content")

    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "extra_field": "not_allowed",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": hash1,
                "cohort": "clear_no_call",
                "cases": [],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"


def test_reject_bool_as_schema_version(tmp_path: Path):
    manifest_dict = {
        "schema_version": True,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"


def test_reject_invalid_identifiers(tmp_path: Path):
    invalid_ids = ["", "invalid id with spaces", "bad@id", "a" * 129]
    for bad_id in invalid_ids:
        manifest_dict = {
            "schema_version": 1,
            "dataset_id": bad_id,
            "dataset_version": "1",
            "split": "tuning",
            "source_root": "fixtures",
            "samples": [],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")

        with pytest.raises(InvalidGoldenSetError) as exc_info:
            load_golden_set_manifest(manifest_path)
        assert exc_info.value.code == "invalid_schema"


def test_reject_invalid_enums_and_hashes(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"content")

    # Invalid split
    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "invalid_split",
        "source_root": "fixtures",
        "samples": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"

    # Invalid SHA256 format (uppercase)
    bad_hash = "sha256:" + "A" * 64
    manifest_dict["split"] = "tuning"
    manifest_dict["samples"] = [
        {
            "sample_id": "sample-01",
            "path": "sample1.xlsx",
            "sha256": bad_hash,
            "cohort": "clear_no_call",
            "cases": [],
        }
    ]
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"


def test_reject_cohort_cases_mismatch(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"content")

    # ambiguous cohort with 0 cases
    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": hash1,
                "cohort": "ambiguous",
                "cases": [],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"

    # clear_no_call with 1 case
    manifest_dict["samples"][0]["cohort"] = "clear_no_call"
    manifest_dict["samples"][0]["cases"] = [
        {
            "label_id": "case-01",
            "sheet_name": "Sheet1",
            "source_range": "A1:B2",
            "expected": "logical_table",
            "fact_digest": "sha256:" + "0" * 64,
            "choices_digest": "sha256:" + "0" * 64,
        }
    ]
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "invalid_schema"


def test_reject_duplicate_ids(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _, hash1 = _make_dummy_file(source_root, "sample1.xlsx", b"content")

    # Duplicate sample_id
    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": hash1,
                "cohort": "clear_no_call",
                "cases": [],
            },
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": hash1,
                "cohort": "clear_no_call",
                "cases": [],
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "duplicate_id"


def test_reject_path_traversal_and_escapes(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _make_dummy_file(tmp_path, "outside.xlsx", b"outside")

    # Try .. to escape source_root
    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "../outside.xlsx",
                "sha256": "sha256:" + "0" * 64,
                "cohort": "clear_no_call",
                "cases": [],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "path_traversal"


def test_reject_file_hash_mismatch(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    _make_dummy_file(source_root, "sample1.xlsx", b"real content")

    manifest_dict = {
        "schema_version": 1,
        "dataset_id": "test-dataset",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": "fixtures",
        "samples": [
            {
                "sample_id": "sample-01",
                "path": "sample1.xlsx",
                "sha256": "sha256:" + "0" * 64,  # wrong hash
                "cohort": "clear_no_call",
                "cases": [],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)
    assert exc_info.value.code == "hash_mismatch"


def test_output_dir_isolation(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()

    # output_dir inside source_root
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        validate_output_dir_isolation(source_root, source_root / "reports")
    assert exc_info.value.code == "input_output_overlap"

    # output_dir equal to source_root
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        validate_output_dir_isolation(source_root, source_root)
    assert exc_info.value.code == "input_output_overlap"

    # output_dir outside source_root - valid
    validate_output_dir_isolation(source_root, tmp_path / "reports")


def test_manifest_source_root_must_be_relative(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    manifest = {
        "schema_version": 1,
        "dataset_id": "absolute-root",
        "dataset_version": "1",
        "split": "tuning",
        "source_root": str(source_root),
        "samples": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        load_golden_set_manifest(manifest_path)

    assert exc_info.value.code == "path_traversal"


def test_canonical_choices_digest():
    c1 = RegionChoice(
        choice_id="c1",
        kind="logical_table",
        local_score=0.85,
        reason_codes=("header_row", "regular_grid"),
    )
    c2 = RegionChoice(
        choice_id="c2",
        kind="form",
        local_score=0.45,
        reason_codes=("key_value_pairs",),
    )

    digest1 = compute_choices_digest([c1, c2])
    digest2 = compute_choices_digest([c1, c2])
    assert digest1 == digest2
    assert digest1.startswith("sha256:")
    assert len(digest1) == 71

    # Order or content change produces different digest
    digest3 = compute_choices_digest([c2, c1])
    assert digest1 != digest3


def test_content_free_evaluation_id():
    eval_id_1 = compute_evaluation_id("d1", "v1", "s1", "l1")
    eval_id_2 = compute_evaluation_id("d1", "v1", "s1", "l1")
    assert eval_id_1 == eval_id_2
    assert eval_id_1.startswith("sha256:")
    assert len(eval_id_1) == 71

    eval_id_diff = compute_evaluation_id("d1", "v1", "s1", "l2")
    assert eval_id_1 != eval_id_diff


def test_sanitized_error_representation():
    err = InvalidGoldenSetError(
        code="hash_mismatch", evaluation_id="sha256:abcdef", message="Digest mismatch"
    )
    assert "Digest mismatch" in str(err)
    assert err.code == "hash_mismatch"
    assert err.evaluation_id == "sha256:abcdef"
