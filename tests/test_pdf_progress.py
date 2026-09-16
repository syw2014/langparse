import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.simple import SimplePDFEngine


def test_simple_reports_pages_before_yield(monkeypatch):
    page = SimpleNamespace(extract_text=lambda: "native text")
    pdf = SimpleNamespace(pages=[page, page])
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _: nullcontext(pdf)))
    events = []
    pages = SimplePDFEngine(enable_ocr=False).process(
        Path("sample.pdf"), progress_callback=events.append
    )
    assert events == []
    assert next(pages).page_number == 1
    assert [(event.completed_units, event.total_units) for event in events] == [(1, 2)]
    assert [page.page_number for page in pages] == [2]
    assert [event.percent for event in events] == [50, 100]
    assert all(event.unit == "pages" and event.state == "running" for event in events)


def test_deepdoc_adapts_progress_and_keeps_phase_completion_local(monkeypatch):
    events = []

    class Parser:
        def parse_into_bboxes(self, path, callback):
            assert events[0].phase == "preparing"
            callback(-0.5)
            callback(0.63, "Layout analysis")
            callback(0.4)
            callback(1.5, "Structured")
            return []

    engine = DeepDocEngine(parser=Parser())
    monkeypatch.setattr(engine, "_classify_ocr_pages", lambda _: {})
    result = engine.process_document(Path("sample.pdf"), progress_callback=events.append)
    assert result.pages == []
    parsing = [event for event in events if event.phase == "parsing"]
    assert [event.percent for event in parsing] == [0, 63, 63, 100]
    assert parsing[1].message == "Layout analysis"
    assert events[-1].phase == "rendering"
    assert all(event.state == "running" for event in events)


def test_deepdoc_without_observer_preserves_parser_call(monkeypatch):
    class Parser:
        def parse_into_bboxes(self, path):
            return []

    engine = DeepDocEngine(parser=Parser())
    monkeypatch.setattr(engine, "_classify_ocr_pages", lambda _: {})
    assert engine.process_document(Path("sample.pdf")).pages == []


def test_mineru_reports_actual_request_boundary_without_leaking_callback(monkeypatch):
    events = []
    engine = MinerUEngine(device="cpu")

    def running_service():
        assert events[-1].phase == "preparing"
        return nullcontext("http://test")

    def parse_file(path, config):
        assert events[-1].phase == "parsing"
        assert "progress_callback" not in config
        assert "progress_callback" not in config["extra_options"]
        return [{"page_number": 1, "markdown": "Result"}]

    monkeypatch.setattr(
        engine, "_create_service_manager", lambda: SimpleNamespace(running_service=running_service)
    )
    monkeypatch.setattr(engine, "_create_client", lambda _: SimpleNamespace(parse_file=parse_file))
    result = list(engine.process(Path("sample.pdf"), progress_callback=events.append))
    assert result[0].markdown_content == "Result"
    assert [event.phase for event in events] == ["preparing", "parsing", "rendering"]
    assert all(event.percent is None for event in events)


def test_mineru_without_observer_preserves_runtime_call(monkeypatch):
    engine = MinerUEngine(device="cpu")
    monkeypatch.setattr(engine, "_run_mineru", lambda path, config: [])
    assert engine.process_document(Path("sample.pdf")).pages == []


def test_pdf_observer_failure_does_not_interrupt_parsing(monkeypatch):
    def broken_callback(event):
        raise RuntimeError("observer failure")

    page = SimpleNamespace(extract_text=lambda: "text")
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(open=lambda _: nullcontext(SimpleNamespace(pages=[page]))),
    )
    result = list(
        SimplePDFEngine(enable_ocr=False).process(
            Path("sample.pdf"), progress_callback=broken_callback
        )
    )
    assert result[0].plain_text == "text"
