from pathlib import Path
from types import SimpleNamespace

import pytest

from langparse.engines.pdf.deepdoc.model_loader import (
    DEEPDOC_MODEL_REVISION,
    REQUIRED_MODEL_FILES,
    default_model_dir,
    download_models,
    ensure_deepdoc_models,
)


@pytest.fixture(autouse=True)
def use_tiny_model_hashes(monkeypatch):
    """Keep model-policy tests fast while exercising the production checksum path."""
    empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    monkeypatch.setattr(
        "langparse.engines.pdf.deepdoc.model_loader.DEEPDOC_MODEL_SHA256",
        dict.fromkeys(REQUIRED_MODEL_FILES, empty_sha256),
    )


def _touch_required_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_MODEL_FILES:
        (directory / name).write_bytes(b"")


def test_default_model_dir_is_under_dot_langparse():
    assert default_model_dir() == Path.home() / ".langparse" / "models" / "deepdoc"


def test_explicit_model_dir_with_required_files_is_used_as_is(tmp_path):
    _touch_required_files(tmp_path)

    resolved = ensure_deepdoc_models(model_dir=str(tmp_path))

    assert resolved == str(tmp_path)


def test_explicit_model_dir_missing_files_raises(tmp_path):
    with pytest.raises(RuntimeError, match="missing required files"):
        ensure_deepdoc_models(model_dir=str(tmp_path))


def test_explicit_model_dir_rejects_corrupted_model_file(tmp_path):
    """Catch existing same-name weights bypassing the pinned upstream revision."""
    _touch_required_files(tmp_path)
    (tmp_path / "det.onnx").write_bytes(b"corrupt")

    with pytest.raises(RuntimeError, match="checksum mismatch.*det.onnx"):
        ensure_deepdoc_models(model_dir=str(tmp_path))


def test_require_existing_policy_raises_when_download_dir_is_empty(tmp_path):
    with pytest.raises(RuntimeError, match="require_existing"):
        ensure_deepdoc_models(download_dir=str(tmp_path), model_policy="require_existing")


def test_require_existing_policy_succeeds_when_files_present(tmp_path):
    _touch_required_files(tmp_path)

    resolved = ensure_deepdoc_models(download_dir=str(tmp_path), model_policy="require_existing")

    assert resolved == str(tmp_path)


def test_download_if_missing_triggers_download(monkeypatch, tmp_path):
    calls = []

    def fake_download_models(local_dir):
        calls.append(local_dir)
        _touch_required_files(Path(local_dir))
        return Path(local_dir)

    monkeypatch.setattr(
        "langparse.engines.pdf.deepdoc.model_loader.download_models", fake_download_models
    )

    resolved = ensure_deepdoc_models(download_dir=str(tmp_path))

    assert resolved == str(tmp_path)
    assert calls == [tmp_path]


def test_download_models_pins_the_upstream_revision(monkeypatch, tmp_path):
    """Catch a mutable Hugging Face branch silently changing production weights."""
    calls = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        return kwargs["local_dir"]

    monkeypatch.setitem(
        __import__("sys").modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=fake_snapshot_download),
    )

    resolved = download_models(tmp_path)

    assert resolved == tmp_path
    assert calls == [
        {
            "repo_id": "InfiniFlow/deepdoc",
            "revision": DEEPDOC_MODEL_REVISION,
            "local_dir": str(tmp_path),
        }
    ]


def test_unsupported_model_policy_raises():
    with pytest.raises(ValueError, match="Unsupported deepdoc model_policy"):
        ensure_deepdoc_models(download_dir="/tmp/whatever", model_policy="bogus")
