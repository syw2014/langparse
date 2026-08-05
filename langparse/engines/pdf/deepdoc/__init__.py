"""
Ported from RAGFlow's deepdoc module (Apache-2.0):
https://github.com/infiniflow/ragflow/tree/main/deepdoc
Copyright 2025 The InfiniFlow Authors.

Ported near-verbatim: geometry, OCR, layout-recognition, and
table-structure-recognition logic is unchanged. Removed or replaced:
- All non-PDF format parsers, the resume parser, and the deepdoc_server
  FastAPI service (out of scope -- langparse has its own docx/excel/
  markdown parsers).
- VisionParser and PlainParser (VisionParser needs an LLM and RAGFlow's
  DB/service stack; PlainParser is a no-OCR pypdf fallback, redundant with
  langparse's own `simple` engine).
- Ascend NPU code paths and the remote DLA HTTP client branch (this port is
  CPU/ONNX-only).
- The XGBoost up/down line-merge classifier (updown_cnt_mdl /
  _updown_concat_features) -- confirmed dead code on the live call path in
  the source revision this was ported from: _concat_downward() returns
  immediately after its first two lines.
- rag_tokenizer (a thin wrapper around a tokenizer bundled in the
  infinity-sdk vector-DB client) -- replaced with tokenizer.py, a small
  jieba-backed shim covering the same call sites (is_chinese/tokenize/tag).
- common.*/rag.* cross-package imports -- replaced with local equivalents
  (see model_loader.py for model directory resolution).

operators.py and postprocess.py are themselves derived from PaddleOCR
(Apache-2.0) upstream in RAGFlow; that attribution carries through here too.
"""

__all__ = ["OCR", "LayoutRecognizer", "Recognizer", "TableStructureRecognizer", "RAGFlowPdfParser"]

# Lazy (PEP 562) exports: importing this package must stay cheap so that
# lightweight submodules (model_loader.py, rendering.py, tokenizer.py) can be
# imported on their own -- e.g. under a `pip install -e ".[dev]"`-only
# environment -- without transitively pulling in sklearn/cv2/onnxruntime via
# pdf_parser.py's own heavy dependency chain. Python always runs a package's
# __init__.py before any of its submodules, so eager `from .x import Y` here
# would make every submodule import pay that cost.
_EXPORTS = {
    "OCR": (".ocr", "OCR"),
    "LayoutRecognizer": (".layout_recognizer", "LayoutRecognizer4YOLOv10"),
    "Recognizer": (".recognizer", "Recognizer"),
    "TableStructureRecognizer": (".table_structure_recognizer", "TableStructureRecognizer"),
    "RAGFlowPdfParser": (".pdf_parser", "RAGFlowPdfParser"),
}


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        module_name, attr_name = _EXPORTS[name]
        module = importlib.import_module(module_name, __name__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
