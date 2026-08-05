from pathlib import Path

import pytest

from langparse.engines.pdf.deepdoc.model_loader import (
    REQUIRED_MODEL_FILES,
    default_model_dir,
    ensure_deepdoc_models,
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


def test_unsupported_model_policy_raises():
    with pytest.raises(ValueError, match="Unsupported deepdoc model_policy"):
        ensure_deepdoc_models(download_dir="/tmp/whatever", model_policy="bogus")
