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
