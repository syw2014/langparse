from __future__ import annotations

from pathlib import Path
from unittest import mock

from langparse.engines.pdf.mineru import MinerUEngine
from langparse.services.batch_service import BatchParseService
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult


def test_mineru_engine_filters_sensitive_credentials_from_kwargs():
    engine = MinerUEngine(
        api_key="sk-secret-key",
        openai_api_key="sk-openai-secret",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        token="bearer-token",
        secret="my-secret",
        custom_param="safe_value",
    )
    # Ensure credentials are never put into extra_options
    assert "api_key" not in engine.extra_options
    assert "openai_api_key" not in engine.extra_options
    assert "model" not in engine.extra_options
    assert "base_url" not in engine.extra_options
    assert "token" not in engine.extra_options
    assert "secret" not in engine.extra_options
    assert engine.extra_options.get("custom_param") == "safe_value"


def test_mineru_engine_filters_sensitive_credentials_from_extra_options():
    """The extra_options dict itself must also be sanitized."""
    engine = MinerUEngine(
        extra_options={
            "api_key": "sk-via-extra",
            "openai_api_key": "sk-openai-via-extra",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "auth": "bearer-auth",
            "safe_option": "keep_me",
        },
    )
    assert "api_key" not in engine.extra_options
    assert "openai_api_key" not in engine.extra_options
    assert "model" not in engine.extra_options
    assert "base_url" not in engine.extra_options
    assert "auth" not in engine.extra_options
    assert engine.extra_options.get("safe_option") == "keep_me"


def test_mineru_engine_filters_sensitive_credentials_at_runtime_egress(
    tmp_path: Path,
    monkeypatch,
):
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"%PDF-1.4 dummy")
    captured: dict[str, object] = {}
    engine = MinerUEngine(device="cpu", extra_options={"constructor_safe": "keep"})

    def fake_run(_path: Path, runtime_config: dict[str, object]):
        captured.update(runtime_config)
        return []

    monkeypatch.setattr(engine, "_run_mineru", fake_run)

    parsed = engine.process_document(
        sample,
        extra_options={
            "api_key": "sk-runtime-secret",
            "authorization": "Bearer runtime-secret",
            "runtime_safe": "keep",
        },
    )

    assert parsed.engine == "mineru"
    assert captured["extra_options"] == {
        "constructor_safe": "keep",
        "runtime_safe": "keep",
    }


def test_batch_service_does_not_leak_model_kwargs_to_engine(tmp_path: Path):
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"%PDF-1.4 dummy")

    mock_engine = mock.MagicMock()
    mock_engine.process_document.return_value = ParsedDocumentResult(
        source=str(sample),
        filename=sample.name,
        engine="mineru",
        markdown_content="parsed",
    )

    service = ParseService()
    with mock.patch.object(service, "create_engine", return_value=mock_engine) as mock_create:
        batch_service = BatchParseService(parse_service=service)
        result = batch_service.run(
            [str(sample)],
            engine_name="mineru",
            output_dir=tmp_path / "out",
            max_workers=1,
            model="gpt-4o",
            api_key="sk-leak-test",
            base_url="https://api.test/v1",
            workbook_disambiguation="auto",
        )
        assert result.success_count == 1
        # Verify kwargs passed to create_engine DO NOT contain api_key, model, base_url, workbook_disambiguation
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert "api_key" not in kwargs
        assert "model" not in kwargs
        assert "base_url" not in kwargs
        assert "workbook_disambiguation" not in kwargs
