import sys
import types
from unittest.mock import patch

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import SimplePDFEngine
from langparse.parsers.pdf_parser import PDFParser
from langparse.types import Document, ParsedElement
from langparse.config import settings


def test_page_result_supports_richer_fields():
    page = PageResult(
        page_number=1,
        markdown_content="# Title",
        plain_text="Title",
        elements=[ParsedElement(kind="heading", text="Title", metadata={})],
        tables=[],
        images=[],
        metadata={"engine_name": "simple"},
    )

    assert page.page_number == 1
    assert page.plain_text == "Title"
    assert page.elements[0].kind == "heading"


def test_normalized_models_are_available():
    from langparse import ParsedDocumentResult, ParsedElement as ExportedParsedElement, ParsedPageResult

    page = ParsedPageResult(
        page_number=1,
        markdown_content="# Title",
        plain_text="Title",
        elements=[ExportedParsedElement(kind="heading", text="Title", metadata={})],
    )
    document = ParsedDocumentResult(
        source="/tmp/input.pdf",
        filename="input.pdf",
        engine="simple",
        pages=[page],
        markdown_content="# Title",
        metadata={"engine": "simple"},
    )

    assert document.pages[0].elements[0].kind == "heading"
    assert document.metadata["engine"] == "simple"


def test_simple_engine_populates_plain_text_metadata(monkeypatch, tmp_path):
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = SimplePDFEngine()

    class DummyPage:
        def extract_text(self):
            return "Hello"

    class DummyPDF:
        pages = [DummyPage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=lambda _: DummyPDF()))
    pages = list(engine.process(pdf_path))

    assert pages[0].plain_text == "Hello"
    assert pages[0].metadata["engine_name"] == "simple"


def test_pdf_parser_returns_document_with_metadata():
    with patch("langparse.engines.pdf.simple.SimplePDFEngine.process") as mock_process:
        mock_process.return_value = iter(
            [
                PageResult(
                    page_number=1,
                    markdown_content="Page 1 content",
                    metadata={"engine_name": "simple"},
                )
            ]
        )

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            parser = PDFParser(engine="simple")
            doc = parser.parse(tmp.name)

    assert isinstance(doc, Document)
    assert doc.metadata["engine"] == "simple"


def test_pdf_parser_simple_engine_flow():
    # Mock the SimplePDFEngine.process method
    with patch('langparse.engines.pdf.simple.SimplePDFEngine.process') as mock_process:
        # Setup mock return values
        mock_process.return_value = iter([
            PageResult(page_number=1, markdown_content="Page 1 content"),
            PageResult(page_number=2, markdown_content="Page 2 content")
        ])
        
        parser = PDFParser(engine="simple")
        # We can pass a dummy path because we mocked the process method
        # But PDFParser checks if file exists first.
        # So we need a real dummy file.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            doc = parser.parse(tmp.name)
            
            assert "<!-- page_number: 1 -->" in doc.content
            assert "Page 1 content" in doc.content
            assert "<!-- page_number: 2 -->" in doc.content
            assert "Page 2 content" in doc.content
            assert doc.metadata['engine'] == 'simple'


def test_pdf_parser_engine_selection():
    parser = PDFParser(engine="mineru")
    assert parser.engine_name == "mineru"
    # assert isinstance(parser.engine, MinerUEngine) # Need to import MinerUEngine to check


def test_pdf_parser_uses_resolved_engine_config(monkeypatch):
    resolved_config = {
        "device": "cpu",
        "model_dir": "/models",
        "download_dir": "/downloads",
        "enable_ocr": False,
    }
    captured = {}

    def fake_resolve_engine_config(engine_name, runtime_kwargs):
        captured["engine_name"] = engine_name
        captured["runtime_kwargs"] = runtime_kwargs
        return resolved_config

    class StubEngine:
        def __init__(self, **kwargs):
            captured["engine_kwargs"] = kwargs

    monkeypatch.setattr(settings, "resolve_engine_config", fake_resolve_engine_config)
    monkeypatch.setitem(__import__("langparse.parsers.pdf_parser", fromlist=["ENGINE_MAP"]).ENGINE_MAP, "mineru", StubEngine)

    parser = PDFParser(engine="mineru", device="cuda")

    assert parser.engine_name == "mineru"
    assert captured["engine_name"] == "mineru"
    assert captured["runtime_kwargs"] == {"device": "cuda"}
    assert captured["engine_kwargs"] == resolved_config
    assert isinstance(parser.engine, StubEngine)


def test_pdf_parser_merges_config_and_runtime_extra_options(monkeypatch):
    original_engine_config = settings.get("engines.mineru", {}).copy()
    monkeypatch.setitem(settings._config["engines"], "mineru", {
        **original_engine_config,
        "extra_options": {"cache_dir": "/cache"},
    })

    captured = {}

    class StubEngine:
        def __init__(self, **kwargs):
            captured["engine_kwargs"] = kwargs

    monkeypatch.setitem(__import__("langparse.parsers.pdf_parser", fromlist=["ENGINE_MAP"]).ENGINE_MAP, "mineru", StubEngine)

    parser = PDFParser(engine="mineru", extra_options={"workers": 4})

    assert parser.engine_name == "mineru"
    assert captured["engine_kwargs"]["extra_options"] == {
        "cache_dir": "/cache",
        "workers": 4,
    }
