import importlib
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_langparse_config_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in (
        "LANGPARSE_DEFAULT_PDF_ENGINE",
        "LANGPARSE_MINERU_DEVICE",
        "LANGPARSE_MINERU_MODEL_DIR",
        "LANGPARSE_MINERU_DOWNLOAD_DIR",
        "LANGPARSE_MINERU_ENABLE_OCR",
        "LANGPARSE_MINERU_API_URL",
        "LANGPARSE_MINERU_API_HOST",
        "LANGPARSE_MINERU_API_PORT",
        "LANGPARSE_MINERU_API_COMMAND",
        "LANGPARSE_MINERU_API_START_TIMEOUT",
        "LANGPARSE_MINERU_MODEL_POLICY",
        "LANGPARSE_MINERU_MODEL_SOURCE",
    ):
        monkeypatch.delenv(key, raising=False)


def load_config_class():
    module_name = "langparse.config"
    if module_name in sys.modules:
        module = importlib.reload(sys.modules[module_name])
    else:
        module = importlib.import_module(module_name)
    return module.Config


def test_env_overrides_file_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".langparse"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text('{"engines": {"mineru": {"device": "cpu"}}}')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LANGPARSE_MINERU_DEVICE", "cuda")

    Config = load_config_class()
    settings = Config()

    assert settings.get("engines.mineru.device") == "cuda"


def test_default_pdf_engine_env_overrides_default(monkeypatch):
    monkeypatch.setenv("LANGPARSE_DEFAULT_PDF_ENGINE", "mineru")

    Config = load_config_class()
    settings = Config()

    assert settings.get("default_pdf_engine") == "mineru"


def test_env_parses_false_string_as_boolean_false(monkeypatch):
    monkeypatch.setenv("LANGPARSE_MINERU_ENABLE_OCR", "False")

    Config = load_config_class()
    settings = Config()

    assert settings.get("engines.mineru.enable_ocr") is False


def test_default_mineru_values_are_exposed():
    Config = load_config_class()
    settings = Config()

    assert settings.get("engines.mineru.device") == "auto"
    assert settings.get("engines.mineru.model_dir") is None
    assert settings.get("engines.mineru.download_dir") is None
    assert settings.get("engines.mineru.enable_ocr") is True
    assert settings.get("engines.mineru.api_url") is None
    assert settings.get("engines.mineru.api_host") == "127.0.0.1"
    assert settings.get("engines.mineru.api_port") == 8000
    assert settings.get("engines.mineru.api_command") == "mineru-api"
    assert settings.get("engines.mineru.api_start_timeout") == 30.0
    assert settings.get("engines.mineru.model_policy") == "download_if_missing"
    assert settings.get("engines.mineru.model_source") is None
    assert settings.get("engines.mineru.extra_options") == {}


def test_get_engine_config_merges_runtime_kwargs():
    Config = load_config_class()
    settings = Config()
    merged = settings.resolve_engine_config(
        "mineru",
        {"device": "cpu", "model_dir": "/tmp/models"},
    )

    assert merged["device"] == "cpu"
    assert merged["model_dir"] == "/tmp/models"
