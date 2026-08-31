"""
Model directory resolution for the deepdoc port, mirroring MinerUEngine's
model_dir/download_dir/model_policy semantics (see
langparse/engines/pdf/mineru_service.py) instead of upstream deepdoc's
per-class try/except-then-snapshot_download pattern repeated four times.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DEEPDOC_REPO_ID = "InfiniFlow/deepdoc"
# Immutable upstream commit resolved from the Hugging Face model metadata.
# Updating model weights is a deliberate release change, never an implicit pull.
DEEPDOC_MODEL_REVISION = "de0e793dc6d744406c96dabd688ccc969f41b443"
REQUIRED_MODEL_FILES = ("det.onnx", "rec.onnx", "layout.onnx", "tsr.onnx", "ocr.res")
DEEPDOC_MODEL_SHA256 = {
    "det.onnx": "30a86f5731181461d08021402766601e4302a9b9b9666be8aff402696339cdff",
    "rec.onnx": "1c7cf60de2afd728d512f4190cf37455092b45f06175365c6fc58d8cd7e2a68b",
    "layout.onnx": "de401c03ee30b1c120416dc06f0705237f0c36d3cdb692c9bfefe8a8f98a4b70",
    "tsr.onnx": "1585f88015c60209f16a079a26d944afca790ab7022fe7d0574113ccb9a6f9b4",
    "ocr.res": "28b2362ad4ab2dc38769aa72feb535e3a9ddb3fd2a7585a05920e6393b1dc7f7",
}


def default_model_dir() -> Path:
    return Path.home() / ".langparse" / "models" / "deepdoc"


def _has_required_files(model_dir: Path) -> bool:
    return _model_validation_error(model_dir) is None


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_validation_error(model_dir: Path) -> str | None:
    missing = [name for name in REQUIRED_MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        return f"missing required files: {tuple(missing)}"

    for name, expected in DEEPDOC_MODEL_SHA256.items():
        actual = _sha256(model_dir / name)
        if actual != expected:
            return f"checksum mismatch for {name}: expected {expected}, got {actual}"
    return None


def download_models(local_dir: Path) -> Path:
    from huggingface_hub import snapshot_download

    downloaded = snapshot_download(
        repo_id=DEEPDOC_REPO_ID,
        revision=DEEPDOC_MODEL_REVISION,
        local_dir=str(local_dir),
    )
    return Path(downloaded)


def ensure_deepdoc_models(
    model_dir: str | None = None,
    download_dir: str | None = None,
    model_policy: str = "download_if_missing",
) -> str:
    if model_policy not in ("download_if_missing", "require_existing"):
        raise ValueError(
            f"Unsupported deepdoc model_policy: {model_policy}. "
            "Expected 'download_if_missing' or 'require_existing'."
        )

    if model_dir:
        target = Path(model_dir).expanduser()
        validation_error = _model_validation_error(target)
        if validation_error is not None:
            raise RuntimeError(
                f"deepdoc model_dir has missing or invalid required files under {target}: "
                f"{validation_error}"
            )
        return str(target)

    target = Path(download_dir).expanduser() if download_dir else default_model_dir()
    if _has_required_files(target):
        return str(target)

    if model_policy == "require_existing":
        raise RuntimeError(
            f"deepdoc model_policy=require_existing but models are missing under {target}"
        )

    target.mkdir(parents=True, exist_ok=True)
    downloaded = download_models(target)
    validation_error = _model_validation_error(downloaded)
    if validation_error is not None:
        raise RuntimeError(f"Downloaded deepdoc models failed verification: {validation_error}")
    return str(downloaded)
