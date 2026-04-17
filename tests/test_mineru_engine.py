import subprocess
from contextlib import contextmanager

import pytest

from langparse.engines.pdf.mineru_client import MinerUClient
from langparse.engines.pdf.mineru_service import MinerUServiceManager
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


def test_ensure_runtime_is_noop_for_api_managed_flow():
    engine = MinerUEngine()

    assert engine._ensure_runtime() is None


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


def test_remote_api_url_bypasses_local_service(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(api_url="http://remote.example:8000")
    captured = {}

    class StubManager:
        @contextmanager
        def running_service(self):
            captured["used_manager"] = True
            yield "http://remote.example:8000"

    class StubClient:
        def parse_file(self, file_path, runtime_config):
            captured["base_url"] = "http://remote.example:8000"
            captured["runtime_config"] = runtime_config
            return [{"page_number": 1, "markdown": "# Remote"}]

    monkeypatch.setattr(engine, "_create_service_manager", lambda: StubManager())
    monkeypatch.setattr(engine, "_create_client", lambda base_url: StubClient())

    parsed = engine.process_document(pdf_path)

    assert captured["used_manager"] is True
    assert parsed.pages[0].markdown_content == "# Remote"


def test_service_manager_starts_local_service_when_api_url_missing(monkeypatch):
    manager = MinerUServiceManager(command="mineru-api", port=8123)
    health_attempts = {"count": 0}

    class StubClient:
        def health(self):
            health_attempts["count"] += 1
            if health_attempts["count"] < 2:
                raise RuntimeError("not ready")
            return {"status": "ok"}

    class StubProcess:
        def poll(self):
            return None
        def terminate(self):
            health_attempts["terminated"] = True
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(manager, "_is_healthy", lambda client: False)
    monkeypatch.setattr(manager, "_start_local_service", lambda: StubProcess())
    monkeypatch.setattr(manager, "_stop_process", lambda process: health_attempts.setdefault("stopped", True))
    monkeypatch.setattr(
        "langparse.engines.pdf.mineru_service.MinerUClient",
        lambda base_url, timeout=300.0: StubClient(),
    )

    with manager.running_service() as base_url:
        assert base_url == "http://127.0.0.1:8123"

    assert health_attempts["count"] >= 2
    assert health_attempts["stopped"] is True


def test_service_manager_raises_clear_error_when_command_missing():
    manager = MinerUServiceManager(command="missing-mineru-api")
    with pytest.raises(RuntimeError, match="Unable to start local mineru-api service"):
        manager._start_local_service()


def test_client_normalizes_content_list_response(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    client = MinerUClient("http://mineru.example")
    response = {
        "markdown": "# Title",
        "content_list": [
            {"page_idx": 0, "type": "text", "text": "Title", "bbox": [0, 0, 10, 10]},
            {"page_idx": 1, "type": "text", "text": "Page 2", "bbox": [0, 0, 10, 10]},
        ],
    }

    pages = client._normalize_parse_response(response)

    assert [page["page_number"] for page in pages] == [1, 2]
    assert pages[0]["plain_text"] == "Title"
    assert pages[1]["elements"][0]["kind"] == "text"
