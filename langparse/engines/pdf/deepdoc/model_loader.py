"""
Model directory resolution for the deepdoc port, mirroring MinerUEngine's
model_dir/download_dir/model_policy semantics (see
langparse/engines/pdf/mineru_service.py) instead of upstream deepdoc's
per-class try/except-then-snapshot_download pattern repeated four times.
"""

from __future__ import annotations

from pathlib import Path

DEEPDOC_REPO_ID = "InfiniFlow/deepdoc"
REQUIRED_MODEL_FILES = ("det.onnx", "rec.onnx", "layout.onnx", "tsr.onnx", "ocr.res")


def default_model_dir() -> Path:
    return Path.home() / ".langparse" / "models" / "deepdoc"


def _has_required_files(model_dir: Path) -> bool:
    return model_dir.exists() and all((model_dir / name).exists() for name in REQUIRED_MODEL_FILES)


def download_models(local_dir: Path) -> Path:
    from huggingface_hub import snapshot_download

    downloaded = snapshot_download(repo_id=DEEPDOC_REPO_ID, local_dir=str(local_dir))
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
        if not _has_required_files(target):
            raise RuntimeError(
                f"deepdoc model_dir is missing required files under {target}: {REQUIRED_MODEL_FILES}"
            )
        return str(target)

    target = Path(download_dir).expanduser() if download_dir else default_model_dir()
    if _has_required_files(target):
        return str(target)

    if model_policy == "require_existing":
        raise RuntimeError(f"deepdoc model_policy=require_existing but models are missing under {target}")

    target.mkdir(parents=True, exist_ok=True)
    downloaded = download_models(target)
    return str(downloaded)
