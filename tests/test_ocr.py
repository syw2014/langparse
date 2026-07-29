"""A scanned PDF must not look like a successful parse.

The sample corpus shows both shapes: a page with no text layer at all, and the
more dangerous one where a watermark leaves a little garbled text so the parse
reports success while the actual content -- an image -- is never read.
"""

from pathlib import Path

import pytest

from langparse.engines.pdf.ocr import needs_ocr, ocr_page_text


def full_page_image(width=595, height=842):
    return {"x0": 0, "x1": width, "top": 0, "bottom": height}


def small_image():
    return {"x0": 10, "x1": 110, "top": 10, "bottom": 110}


class FakePage:
    def __init__(self, text="", images=(), width=595, height=842):
        self._text = text
        self.images = list(images)
        self.width = width
        self.height = height

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return []

    def to_image(self, resolution=150):
        raise AssertionError("rasterisation should only happen when OCR runs")


def test_page_with_plenty_of_text_does_not_need_ocr():
    page = FakePage(text="word " * 400, images=[full_page_image()])

    assert needs_ocr(page) is False


def test_page_with_no_text_layer_needs_ocr():
    page = FakePage(text="", images=[full_page_image()])

    assert needs_ocr(page) is True


def test_watermark_only_page_needs_ocr():
    """Measured from data/domain/scan.pdf: 145 characters of rotated watermark
    over a full-page image. Text length alone does not distinguish this from a
    sparse but genuine text page -- the full-page image is what gives it away."""
    page = FakePage(text="x" * 145, images=[full_page_image()])

    assert needs_ocr(page) is True


def test_short_text_page_without_images_does_not_need_ocr():
    """A genuinely short text page has nothing for OCR to recover."""
    page = FakePage(text="Short.", images=[])

    assert needs_ocr(page) is False


def test_sparse_text_beside_a_small_figure_does_not_need_ocr():
    """A figure occupying a corner is not a scan; its page text is the real content."""
    page = FakePage(text="A caption and a little prose.", images=[small_image()])

    assert needs_ocr(page) is False


def test_ocr_page_text_joins_recognised_lines():
    class FakeRecogniser:
        def __call__(self, image):
            return [
                [[[0, 0], [1, 0], [1, 1], [0, 1]], "first line", 0.99],
                [[[0, 2], [1, 2], [1, 3], [0, 3]], "second line", 0.98],
            ], 0.1

    class RasterisablePage(FakePage):
        def to_image(self, resolution=150):
            class Wrapper:
                original = object()

            return Wrapper()

    text = ocr_page_text(RasterisablePage(), FakeRecogniser())

    assert text == "first line\nsecond line"


def test_ocr_page_text_is_empty_when_nothing_is_recognised():
    class RasterisablePage(FakePage):
        def to_image(self, resolution=150):
            class Wrapper:
                original = object()

            return Wrapper()

    assert ocr_page_text(RasterisablePage(), lambda image: (None, 0.0)) == ""


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_pdfplumber(monkeypatch, pages):
    import sys
    import types

    module = types.ModuleType("pdfplumber")
    module.open = lambda path: FakePdf(pages)
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


class ScannedPage(FakePage):
    def to_image(self, resolution=150):
        class Wrapper:
            original = object()

        return Wrapper()


def _recogniser(text):
    def call(image):
        return [[None, text, 0.99]], 0.1

    return call


def test_simple_engine_falls_back_to_ocr_on_a_scanned_page(monkeypatch):
    from langparse.engines.pdf.simple import SimplePDFEngine

    _patch_pdfplumber(monkeypatch, [ScannedPage(text="", images=[full_page_image()])])
    engine = SimplePDFEngine(enable_ocr=True, recogniser=_recogniser("recovered text"))

    pages = list(engine.process(Path("scan.pdf")))

    assert pages[0].plain_text == "recovered text"
    assert pages[0].metadata["ocr_applied"] is True


def test_simple_engine_leaves_text_pages_alone(monkeypatch):
    from langparse.engines.pdf.simple import SimplePDFEngine

    _patch_pdfplumber(monkeypatch, [ScannedPage(text="real " * 400, images=[full_page_image()])])
    engine = SimplePDFEngine(enable_ocr=True, recogniser=_recogniser("should not appear"))

    pages = list(engine.process(Path("doc.pdf")))

    assert "should not appear" not in pages[0].plain_text
    assert pages[0].metadata["ocr_applied"] is False


def test_ocr_is_opt_out(monkeypatch):
    from langparse.engines.pdf.simple import SimplePDFEngine

    _patch_pdfplumber(monkeypatch, [ScannedPage(text="", images=[full_page_image()])])
    engine = SimplePDFEngine(enable_ocr=False, recogniser=_recogniser("recovered"))

    pages = list(engine.process(Path("scan.pdf")))

    assert pages[0].plain_text == ""
    assert pages[0].metadata["ocr_applied"] is False


def test_document_metadata_reports_ocr_so_metrics_can_see_it(monkeypatch):
    from langparse.engines.pdf.simple import SimplePDFEngine
    from langparse.metrics import collect_parse_metrics
    from langparse.services.parse_service import ParseService

    _patch_pdfplumber(monkeypatch, [ScannedPage(text="", images=[full_page_image()])])
    engine = SimplePDFEngine(enable_ocr=True, recogniser=_recogniser("recovered text"))

    monkeypatch.setattr(Path, "exists", lambda self: True)
    parsed = ParseService().parse_result("scan.pdf", engine_name="simple", engine=engine)
    metrics = collect_parse_metrics(parsed, 1.0)

    assert metrics.ocr_applied is True
    assert metrics.ocr_text_chars == len("recovered text")


def test_recogniser_is_built_once_under_concurrent_pages(monkeypatch):
    """Batch runs share one engine across threads; model loading costs ~40s."""
    import threading
    import time

    from langparse.engines.pdf import simple as simple_module
    from langparse.engines.pdf.simple import SimplePDFEngine

    builds = []

    def slow_load():
        builds.append(1)
        time.sleep(0.05)
        return lambda image: ([], 0)

    monkeypatch.setattr(simple_module, "load_recogniser", slow_load, raising=False)

    engine = SimplePDFEngine(enable_ocr=True)
    threads = [threading.Thread(target=engine._resolve_recogniser) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(builds) == 1


def test_concurrent_recognition_is_serialised(monkeypatch):
    """rapidocr documents no thread-safety guarantee, so calls must not overlap."""
    import threading
    import time

    overlaps = []
    active = []

    def recogniser(image):
        active.append(1)
        if len(active) > 1:
            overlaps.append(1)
        # sleep releases the GIL, so unsynchronised threads reliably overlap here.
        time.sleep(0.05)
        active.pop()
        return [[None, "text", 0.9]], 0.1

    from langparse.engines.pdf.simple import SimplePDFEngine

    engine = SimplePDFEngine(enable_ocr=True, recogniser=recogniser)
    page = ScannedPage(text="", images=[full_page_image()])

    threads = [threading.Thread(target=engine._run_ocr, args=(page,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert overlaps == []
