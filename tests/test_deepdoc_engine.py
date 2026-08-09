import logging
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.types import ParsedDocumentResult


class _FakePdfplumberPage:
    def __init__(self, text="plenty of native text " * 50, images=()):
        self._text = text
        self.images = list(images)
        self.width = 595
        self.height = 842

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_pdfplumber(monkeypatch, pages):
    module = types.ModuleType("pdfplumber")
    module.open = lambda path: _FakePdf(pages)
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


@pytest.fixture(autouse=True)
def _default_pdfplumber(monkeypatch):
    """process_document() now classifies each page via pdfplumber
    (DeepDocEngine._classify_ocr_pages). Default every test in this file to
    pages with plenty of native text and no images (needs_ocr() -> False), so
    tests that don't care about OCR classification aren't broken by the
    placeholder `%PDF-1.4` bytes they write as a fake PDF file. Tests that do
    care call _patch_pdfplumber again themselves to override this."""
    _patch_pdfplumber(monkeypatch, [_FakePdfplumberPage() for _ in range(10)])


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
    # The default _default_pdfplumber fixture classifies this page as
    # born-digital (plenty of native text, no images), so it must NOT be
    # credited to OCR -- deepdoc no longer hardcodes ocr_applied=True.
    assert parsed.metadata["ocr_applied"] is False
    assert parsed.metadata["ocr_text_chars"] == 0


def test_process_document_reports_ocr_applied_for_a_scanned_looking_page(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    _patch_pdfplumber(
        monkeypatch,
        [_FakePdfplumberPage(text="", images=[{"x0": 0, "x1": 595, "top": 0, "bottom": 842}])],
    )
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "recovered text",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert parsed.metadata["ocr_applied"] is True
    assert parsed.metadata["ocr_text_chars"] == len("recovered text")


def test_process_document_rolls_up_ocr_metadata_across_mixed_pages(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    _patch_pdfplumber(
        monkeypatch,
        [
            _FakePdfplumberPage(),  # page 1: born-digital
            _FakePdfplumberPage(
                text="", images=[{"x0": 0, "x1": 595, "top": 0, "bottom": 842}]
            ),  # page 2: scanned
        ],
    )
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "native page",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
            {
                "page_number": 2,
                "layout_type": "text",
                "text": "scanned page",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    # any() across pages: True because page 2 is scanned, even though page 1 isn't.
    assert parsed.metadata["ocr_applied"] is True
    # sum() across pages: only page 2's chars count, matching mineru.py's rollup.
    assert parsed.metadata["ocr_text_chars"] == len("scanned page")


def test_process_document_survives_ocr_classification_failure(tmp_path, monkeypatch, caplog):
    """Finding 1 regression: _classify_ocr_pages runs *after*
    parse_into_bboxes() has already spent time on the real parse, purely to
    annotate advisory ocr_applied/ocr_text_chars metadata. A pdfplumber
    failure here (malformed/encrypted/oddly-structured PDF, PDFSyntaxError,
    etc.) must never propagate and discard an otherwise-successful parse --
    it should be logged and treated as "classify nothing" (empty dict),
    which is exactly render_pages()'s documented default of False/0 for a
    page absent from the map.
    """
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def _raise_open(path):
        raise Exception("boom: malformed or encrypted PDF")

    module = types.ModuleType("pdfplumber")
    module.open = _raise_open
    monkeypatch.setitem(sys.modules, "pdfplumber", module)

    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "recovered text",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    with caplog.at_level(logging.WARNING, logger="langparse"):
        parsed = engine.process_document(pdf_path)

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.pages[0].markdown_content == "recovered text"
    assert parsed.metadata["ocr_applied"] is False
    assert parsed.metadata["ocr_text_chars"] == 0
    assert "boom: malformed or encrypted PDF" in caplog.text


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
