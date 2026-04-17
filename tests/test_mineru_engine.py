import builtins

import pytest

from langparse.engines.pdf.mineru import MinerUEngine
from langparse.types import ParsedDocumentResult, ParsedPageResult


def test_cuda_mode_requires_available_gpu(monkeypatch):
    engine = MinerUEngine(device="cuda")
    monkeypatch.setattr(engine, "_cuda_available", lambda: False)

    with pytest.raises(RuntimeError, match="CUDA"):
        engine._resolve_device()


def test_auto_mode_prefers_cuda_when_available(monkeypatch):
    engine = MinerUEngine(device="auto")
    monkeypatch.setattr(engine, "_cuda_available", lambda: True)

    assert engine._resolve_device() == "cuda"


def test_process_document_returns_normalized_result(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(device="cpu", model_dir="/models")
    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)
    monkeypatch.setattr(
        engine,
        "_run_mineru",
        lambda path, runtime_config: [{"page_number": 1, "markdown": "# Title"}],
    )

    parsed = engine.process_document(pdf_path)

    assert parsed.engine == "mineru"
    assert parsed.pages[0].markdown_content == "# Title"


def test_process_document_passes_normalized_runtime_config(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(
        device="auto",
        model_dir="/models",
        download_dir="/downloads",
        enable_ocr=True,
        cache_dir="/cache",
    )
    captured = {}

    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)
    monkeypatch.setattr(engine, "_cuda_available", lambda: True)

    def fake_run_mineru(path, runtime_config):
        captured["path"] = path
        captured["runtime_config"] = runtime_config
        return [{"page_number": 1, "markdown": "# Title"}]

    monkeypatch.setattr(engine, "_run_mineru", fake_run_mineru)

    parsed = engine.process_document(pdf_path, enable_ocr=False)

    assert parsed.metadata["device"] == "cuda"
    assert captured["path"] == pdf_path
    assert captured["runtime_config"] == {
        "device": "cuda",
        "model_dir": "/models",
        "download_dir": "/downloads",
        "enable_ocr": False,
        "extra_options": {"cache_dir": "/cache"},
    }


def test_constructor_flattens_config_derived_extra_options(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(
        device="cpu",
        extra_options={"cache_dir": "/cache"},
        workers=4,
    )
    captured = {}

    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)

    def fake_run_mineru(path, runtime_config):
        captured["runtime_config"] = runtime_config
        return [{"page_number": 1, "markdown": "# Title"}]

    monkeypatch.setattr(engine, "_run_mineru", fake_run_mineru)

    engine.process_document(pdf_path)

    assert captured["runtime_config"]["extra_options"] == {
        "cache_dir": "/cache",
        "workers": 4,
    }


def test_process_document_tolerates_runtime_kwargs(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(device="cpu", model_dir="/models")
    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)
    monkeypatch.setattr(engine, "_cuda_available", lambda: True)
    monkeypatch.setattr(
        engine,
        "_run_mineru",
        lambda path, runtime_config: [{"page_number": 1, "markdown": "# Title"}],
    )

    parsed = engine.process_document(
        pdf_path,
        device="cuda",
        model_dir="/override",
        enable_ocr=False,
    )

    assert parsed.engine == "mineru"
    assert parsed.metadata["device"] == "cuda"
    assert parsed.metadata["model_dir"] == "/override"
    assert parsed.metadata["enable_ocr"] is False


def test_ensure_runtime_raises_clear_error_when_dependency_missing(monkeypatch):
    engine = MinerUEngine()
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "magic_pdf":
            raise ImportError("missing magic_pdf")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="magic-pdf"):
        engine._ensure_runtime()


def test_process_forwards_runtime_kwargs(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(device="cpu")
    captured = {}

    def fake_process_document(path, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return ParsedDocumentResult(
            source=str(path),
            filename=path.name,
            engine="mineru",
            pages=[
                ParsedPageResult(
                    page_number=1,
                    markdown_content="# Title",
                )
            ],
            markdown_content="# Title",
            metadata={"device": "cpu"},
        )

    monkeypatch.setattr(engine, "process_document", fake_process_document)

    pages = list(engine.process(pdf_path, device="cuda", enable_ocr=False))

    assert captured["path"] == pdf_path
    assert captured["kwargs"] == {"device": "cuda", "enable_ocr": False}
    assert pages[0].markdown_content == "# Title"
