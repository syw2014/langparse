import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.types import ParsedDocumentResult


class _FakeParser:
    def __init__(self, boxes):
        self._boxes = boxes
        self.calls = []

    def parse_into_bboxes(self, fnm, **kwargs):
        self.calls.append(fnm)
        return self._boxes


class _ConcurrencyTrackingParser:
    """Records whether parse_into_bboxes was ever entered by two threads at once.

    RAGFlowPdfParser is per-parse stateful (see DeepDocEngine._parser_lock's
    docstring), so concurrent calls must never overlap. This fake sleeps
    between "starting" and "returning" to widen the race window, and uses an
    instance-level counter that must never exceed 1 if DeepDocEngine's lock
    is doing its job.
    """

    def __init__(self, boxes):
        self._boxes = boxes
        self._active = 0
        self._lock = threading.Lock()
        self.max_concurrent_calls = 0

    def parse_into_bboxes(self, fnm, **kwargs):
        with self._lock:
            self._active += 1
            self.max_concurrent_calls = max(self.max_concurrent_calls, self._active)
        # Sleep *outside* the bookkeeping lock, and after recording entry, so
        # a second thread that (incorrectly) entered concurrently has a wide
        # window to be observed above before either thread returns.
        time.sleep(0.05)
        with self._lock:
            self._active -= 1
        return self._boxes


def test_rejects_non_cpu_device():
    with pytest.raises(ValueError, match="cpu"):
        DeepDocEngine(device="cuda")


def test_process_document_returns_normalized_result(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "title",
                "text": "Title",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.engine == "deepdoc"
    assert parsed.filename == "sample.pdf"
    assert parsed.pages[0].markdown_content == "# Title"
    assert fake_parser.calls == [str(pdf_path)]
    # deepdoc OCRs every page unconditionally, so downstream quality/benchmark
    # checks that gate on OCR having run (langparse/metrics.py,
    # langparse/services/quality.py) must see it reflected here.
    assert parsed.metadata["ocr_applied"] is True
    expected_chars = sum(len(page.plain_text) for page in parsed.pages)
    assert expected_chars == len("Title")
    assert parsed.metadata["ocr_text_chars"] == expected_chars


def test_process_document_joins_page_markdown(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "one",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
            {
                "page_number": 2,
                "layout_type": "text",
                "text": "two",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert parsed.markdown_content == "one\n\ntwo"
    assert len(parsed.pages) == 2


def test_process_yields_page_results(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "hi",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    pages = list(engine.process(pdf_path))

    assert len(pages) == 1
    assert pages[0].markdown_content == "hi"


def test_missing_deepdoc_extra_raises_actionable_import_error(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = DeepDocEngine()

    def fake_import(name, *args, **kwargs):
        if name.startswith("langparse.engines.pdf.deepdoc"):
            raise ImportError("no module named onnxruntime")
        return real_import(name, *args, **kwargs)

    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="langparse\\[deepdoc\\]"):
        engine.process_document(pdf_path)


def test_concurrent_process_document_calls_do_not_overlap(tmp_path):
    """Regression test: batch_service.py builds ONE DeepDocEngine and runs a
    ThreadPoolExecutor over it. RAGFlowPdfParser is stateful across its whole
    call (not just at construction), so DeepDocEngine._parser_lock must be
    held around the entire parse_into_bboxes call, not just the lazy build.
    """
    pdf_path_a = tmp_path / "a.pdf"
    pdf_path_b = tmp_path / "b.pdf"
    pdf_path_a.write_bytes(b"%PDF-1.4")
    pdf_path_b.write_bytes(b"%PDF-1.4")
    box = {
        "page_number": 1,
        "layout_type": "text",
        "text": "hi",
        "x0": 0,
        "x1": 1,
        "top": 0,
        "bottom": 1,
    }
    fake_parser = _ConcurrencyTrackingParser([box])
    engine = DeepDocEngine(parser=fake_parser)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(engine.process_document, pdf_path_a),
            executor.submit(engine.process_document, pdf_path_b),
        ]
        for future in futures:
            future.result()

    assert fake_parser.max_concurrent_calls == 1
